from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from rest_framework import status
from rest_framework.test import APIClient

from chat.models import (
    ChatBotInstance,
    Company,
    Document,
    Credential,
    JiraSync,
    ConfluenceSync,
    JiraIssue,
    JiraComment,
)
from chat.utils.embeddings import search_documents
from chat.utils.jira import ingest_jira_issue
from django.utils import timezone


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
            source="jira_issue",
            source_id="DOC-1",
            content="Primary chatbot document",
            embedding=self.matching_embedding,
        )
        self.primary_document_additional = Document.objects.create(
            company=self.company,
            chatbot=self.primary_chatbot,
            source="jira_issue",
            source_id="DOC-2",
            content="Another document for the primary chatbot",
            embedding=self.alt_embedding,
        )
        self.secondary_document = Document.objects.create(
            company=self.company,
            chatbot=self.secondary_chatbot,
            source="jira_issue",
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


class JiraIngestionSourceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Ingestion Co")
        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Ingestion Bot",
        )
        self.sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )
        self.issue = JiraIssue.objects.create(
            sync=self.sync,
            issue_key="TEST-1",
            summary="Sample issue",
            description="Issue description",
            status="To Do",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self.comment = JiraComment.objects.create(
            issue=self.issue,
            author="Commenter",
            content="A helpful comment",
            created_at=timezone.now(),
        )

    @patch("chat.utils.embeddings.embed_text", return_value=[0.1] * 1536)
    def test_ingest_jira_issue_uses_canonical_sources(self, mock_embed_text):
        ingest_jira_issue(
            company=self.company,
            chatbot=self.chatbot,
            issue=self.issue,
            comments=[self.comment],
        )

        documents = Document.objects.filter(company=self.company, chatbot=self.chatbot)

        self.assertEqual(documents.count(), 2)
        sources = {(doc.source, doc.source_id) for doc in documents}
        expected_comment_id = f"{self.issue.issue_key}_comment_{self.comment.id}"
        self.assertSetEqual(
            sources,
            {
                ("jira_issue", self.issue.issue_key),
                ("jira_comment", expected_comment_id),
            },
        )

        self.assertEqual(mock_embed_text.call_count, 2)


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


    def test_jira_sync_create_accepts_valid_payload(self):
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/"
        payload = {
            'board_url': 'https://example.atlassian.net',
            'credential_id': self.tenant_credential.id,
            'sync_interval': JiraSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(JiraSync.objects.filter(chatBot=self.chatbot).count(), 1)
        sync = JiraSync.objects.get(chatBot=self.chatbot)
        self.assertEqual(sync.credential, self.tenant_credential)

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

    def test_confluence_sync_create_accepts_valid_payload(self):
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/"
        payload = {
            'space_url': 'https://example.atlassian.net/wiki',
            'credential_id': self.tenant_credential.id,
            'sync_interval': ConfluenceSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfluenceSync.objects.filter(chatBot=self.chatbot).count(), 1)
        sync = ConfluenceSync.objects.get(chatBot=self.chatbot)
        self.assertEqual(sync.credential, self.tenant_credential)

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


class UserPasswordUpdateTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Password Co")
        self.user = User.objects.create_user(
            username="password-user",
            email="password@example.com",
            password="initialPass123",
            company=self.company,
        )
        self.client.force_authenticate(self.user)

    def test_patch_user_password_hashes_and_allows_login(self):
        url = reverse('user-detail', args=[self.user.id])
        response = self.client.patch(
            url,
            {'password': 'UpdatedPass456'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('UpdatedPass456'))
        self.assertNotEqual(self.user.password, 'UpdatedPass456')

        login_client = APIClient()
        login_response = login_client.post(
            '/api/login/',
            {'username': self.user.username, 'password': 'UpdatedPass456'},
            format='json',
        )

        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn('token', login_response.data)
