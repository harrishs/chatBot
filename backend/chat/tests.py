from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APIClient

from chat.models import ChatBotInstance, Company, Document, Credential, JiraSync, ConfluenceSync
from chat.utils.embeddings import search_documents


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


class SyncCredentialPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.company = Company.objects.create(name="Tenant A")
        self.other_company = Company.objects.create(name="Tenant B")
        self.user = User.objects.create_user(
            username="tenant-user",
            email="tenant@example.com",
            password="password123",
            company=self.company,
        )

        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Support Bot",
        )

        self.tenant_credential = Credential.objects.create(
            company=self.company,
            name="Tenant Cred",
            email="tenant-cred@example.com",
            _api_key="dummy",
        )

        self.foreign_credential = Credential.objects.create(
            company=self.other_company,
            name="Foreign Cred",
            email="foreign-cred@example.com",
            _api_key="dummy",
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_jira_sync_create_rejects_foreign_credential(self):
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/"
        payload = {
            'board_url': 'https://example.atlassian.net',
            'credential_id': self.foreign_credential.id,
            'sync_interval': JiraSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_jira_sync_update_rejects_foreign_credential(self):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url='https://example.atlassian.net',
            credential=self.tenant_credential,
        )
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/{sync.id}/"

        response = self.client.patch(
            url,
            {'credential_id': self.foreign_credential.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_confluence_sync_create_rejects_foreign_credential(self):
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/"
        payload = {
            'space_url': 'https://example.atlassian.net/wiki',
            'credential_id': self.foreign_credential.id,
            'sync_interval': ConfluenceSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_confluence_sync_update_rejects_foreign_credential(self):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url='https://example.atlassian.net/wiki',
            credential=self.tenant_credential,
        )
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/{sync.id}/"

        response = self.client.patch(
            url,
            {'credential_id': self.foreign_credential.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
