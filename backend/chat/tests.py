from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

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


class CompanyPermissionsTests(APITestCase):
    def setUp(self):
        self.company_one = Company.objects.create(name="Company One")
        self.company_two = Company.objects.create(name="Company Two")

        self.regular_user = User.objects.create_user(
            username="regular",
            email="regular@example.com",
            password="password123",
            company=self.company_one,
        )

        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password123",
            company=self.company_one,
            is_staff=True,
        )

    def test_non_admin_list_is_limited_to_their_company(self):
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.get(reverse("company-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.company_one.id)

    def test_non_admin_cannot_update_other_company(self):
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("company-detail", args=[self.company_two.id])
        response = self.client.patch(url, {"name": "Updated"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.company_two.refresh_from_db()
        self.assertEqual(self.company_two.name, "Company Two")

    def test_non_admin_cannot_update_their_own_company(self):
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("company-detail", args=[self.company_one.id])
        response = self.client.patch(url, {"name": "Updated"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.company_one.refresh_from_db()
        self.assertEqual(self.company_one.name, "Company One")

    def test_admin_can_update_any_company(self):
        self.client.force_authenticate(user=self.admin_user)

        url = reverse("company-detail", args=[self.company_two.id])
        response = self.client.patch(url, {"name": "Updated"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company_two.refresh_from_db()
        self.assertEqual(self.company_two.name, "Updated")
