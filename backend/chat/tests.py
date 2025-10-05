from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from chat.models import ChatBotInstance, Company, Document
from chat.utils.embeddings import search_documents


User = get_user_model()


class SearchDocumentsTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Company")
        self.primary_chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Assistant A",
        )
        self.secondary_chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Assistant B",
        )

        self.matching_embedding = self._unit_vector(0)
        self.alt_embedding = self._unit_vector(1)
        self.secondary_embedding = self._unit_vector(2)

        self.primary_document = Document.objects.create(
            company=self.company,
            chatbot=self.primary_chatbot,
            source="jira",
            source_id="DOC-1",
            content="Primary chatbot document",
            embedding=self.matching_embedding,
        )
        self.primary_document_additional = Document.objects.create(
            company=self.company,
            chatbot=self.primary_chatbot,
            source="jira",
            source_id="DOC-2",
            content="Another document for the primary chatbot",
            embedding=self.alt_embedding,
        )
        self.secondary_document = Document.objects.create(
            company=self.company,
            chatbot=self.secondary_chatbot,
            source="jira",
            source_id="DOC-3",
            content="Secondary chatbot document",
            embedding=self.secondary_embedding,
        )

    def _unit_vector(self, index):
        vector = [0.0] * 1536
        vector[index] = 1.0
        return vector

    @patch("chat.utils.embeddings.embed_text")
    def test_search_documents_filters_results_by_chatbot(self, mock_embed_text):
        mock_embed_text.return_value = self.matching_embedding

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.primary_chatbot.id,
            query="What documents exist?",
            top_k=5,
        )

        mock_embed_text.assert_called_once_with("What documents exist?")

        self.assertEqual(len(results), 2)

        result_ids = {result["id"] for result in results}

        self.assertSetEqual(
            result_ids,
            {self.primary_document.id, self.primary_document_additional.id},
        )

        self.assertNotIn(self.secondary_document.id, result_ids)


class CompanyPermissionsTestCase(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Alpha", website="https://alpha.example")
        self.other_company = Company.objects.create(name="Beta", website="https://beta.example")

        self.user = User.objects.create_user(
            username="user-alpha",
            password="password123",
            email="user-alpha@example.com",
            company=self.company,
        )

        self.admin = User.objects.create_user(
            username="admin-alpha",
            password="password123",
            email="admin-alpha@example.com",
            company=self.company,
        )
        self.admin.is_staff = True
        self.admin.save()

        self.superuser = User.objects.create_superuser(
            username="super-alpha",
            password="password123",
            email="super-alpha@example.com",
            company=self.company,
        )

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def test_list_scoped_to_user_company(self):
        self.authenticate()
        url = reverse('company-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.company.id)

    def test_retrieve_other_company_not_found(self):
        self.authenticate()
        url = reverse('company-detail', args=[self.other_company.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_non_admin_cannot_update_other_company(self):
        self.authenticate()
        url = reverse('company-detail', args=[self.other_company.id])
        response = self.client.patch(url, {'name': 'New Name'}, format='json')

        self.assertEqual(response.status_code, 404)

    def test_non_admin_cannot_update_own_company(self):
        self.authenticate()
        url = reverse('company-detail', args=[self.company.id])
        response = self.client.patch(url, {'name': 'New Name'}, format='json')

        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_company_details(self):
        self.authenticate(self.admin)
        url = reverse('company-detail', args=[self.company.id])
        response = self.client.patch(url, {'name': 'Updated Name', 'website': 'https://new.example'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')
        self.assertEqual(response.data['website'], 'https://new.example')

    def test_admin_cannot_update_other_company(self):
        self.authenticate(self.admin)
        url = reverse('company-detail', args=[self.other_company.id])
        response = self.client.patch(url, {'name': 'Other Name'}, format='json')

        self.assertEqual(response.status_code, 404)

    def test_superuser_can_update_restricted_fields(self):
        self.authenticate(self.superuser)
        url = reverse('company-detail', args=[self.company.id])
        response = self.client.patch(
            url,
            {'name': 'Super Updated', 'website': 'https://super.example'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Super Updated')
        self.assertEqual(response.data['website'], 'https://super.example')
