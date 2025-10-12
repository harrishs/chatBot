import os
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


os.environ.setdefault("ENCRYPTION_KEY", "8wfsecdopt6Fz6ZRlo6RLWF2zOWITlzv9uVSXnscJFA=")


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
            source_id="DOC-1",
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

    @patch("chat.utils.embeddings.embed_text", return_value=[0.1] * 1536)
    def test_ingest_jira_issue_allows_duplicate_source_ids_across_chatbots(self, mock_embed_text):
        other_chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Second Bot",
        )
        other_sync = JiraSync.objects.create(
            chatBot=other_chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/2",
        )
        other_issue = JiraIssue.objects.create(
            sync=other_sync,
            issue_key=self.issue.issue_key,
            summary="Sample issue",
            description="Issue description",
            status="To Do",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        other_comment = JiraComment.objects.create(
            issue=other_issue,
            author="Second Commenter",
            content="Another helpful comment",
            created_at=timezone.now(),
        )

        ingest_jira_issue(
            company=self.company,
            chatbot=self.chatbot,
            issue=self.issue,
            comments=[self.comment],
        )

        ingest_jira_issue(
            company=self.company,
            chatbot=other_chatbot,
            issue=other_issue,
            comments=[other_comment],
        )

        jira_issue_documents = Document.objects.filter(
            company=self.company,
            source="jira_issue",
            source_id=self.issue.issue_key,
        )

        self.assertEqual(jira_issue_documents.count(), 2)


class ChatbotAccessAPITests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Primary Co")
        self.other_company = Company.objects.create(name="Secondary Co")

        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Primary Bot",
        )
        self.other_chatbot = ChatBotInstance.objects.create(
            company=self.other_company,
            name="Secondary Bot",
        )

        self.user = User.objects.create_user(
            username="primary-user",
            email="primary@example.com",
            password="strongpassword123",
            company=self.company,
        )

        self.client.force_authenticate(self.user)

        self.query_url = f"/api/chatbots/{self.chatbot.id}/query/"
        self.other_query_url = f"/api/chatbots/{self.other_chatbot.id}/query/"
        self.chat_url = f"/api/chatbots/{self.chatbot.id}/chat/"
        self.other_chat_url = f"/api/chatbots/{self.other_chatbot.id}/chat/"

    @patch("chat.views.search_documents")
    def test_query_documents_returns_results_for_own_chatbot(self, mock_search_documents):
        mock_search_documents.return_value = [{"id": 1, "score": 0.9}]

        response = self.client.post(
            self.query_url,
            {"query": "Hello", "top_k": 3},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_search_documents.assert_called_once_with(
            self.company.id,
            self.chatbot.id,
            "Hello",
            3,
        )

    @patch("chat.views.search_documents")
    def test_query_documents_other_company_chatbot_returns_404(self, mock_search_documents):
        response = self.client.post(
            self.other_query_url,
            {"query": "Hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_search_documents.assert_not_called()

    @patch("chat.views.generate_answer")
    def test_chat_with_bot_returns_response_for_own_chatbot(self, mock_generate_answer):
        mock_generate_answer.return_value = {"answer": "Hi there"}

        response = self.client.post(
            self.chat_url,
            {"query": "Hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_generate_answer.assert_called_once_with(
            self.company.id,
            self.chatbot.id,
            "Hello",
            top_k=5,
        )

    @patch("chat.views.generate_answer")
    def test_chat_with_bot_other_company_chatbot_returns_404(self, mock_generate_answer):
        response = self.client.post(
            self.other_chat_url,
            {"query": "Hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_generate_answer.assert_not_called()


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


class SyncCredentialValidationTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Tenant Co")
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
        self.credential = Credential.objects.create(
            company=self.company,
            name="Tenant Cred",
            email="tenant-cred@example.com",
            _api_key="dummy",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_jira_sync_create_with_non_numeric_credential_id_returns_400(self):
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/"
        payload = {
            'board_url': 'https://example.atlassian.net',
            'credential_id': 'not-a-number',
            'sync_interval': JiraSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credential_id', response.data)

    def test_jira_sync_update_with_non_numeric_credential_id_returns_400(self):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url='https://example.atlassian.net',
            credential=self.credential,
        )
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/{sync.id}/"
        payload = {
            'board_url': sync.board_url,
            'credential_id': 'not-a-number',
            'sync_interval': sync.sync_interval,
        }

        response = self.client.put(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credential_id', response.data)

    def test_confluence_sync_create_with_non_numeric_credential_id_returns_400(self):
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/"
        payload = {
            'space_url': 'https://example.atlassian.net/wiki',
            'credential_id': 'not-a-number',
            'sync_interval': ConfluenceSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credential_id', response.data)

    def test_confluence_sync_update_with_non_numeric_credential_id_returns_400(self):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url='https://example.atlassian.net/wiki',
            credential=self.credential,
        )
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/{sync.id}/"
        payload = {
            'space_url': sync.space_url,
            'credential_id': 'not-a-number',
            'sync_interval': sync.sync_interval,
        }

        response = self.client.put(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credential_id', response.data)


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
        session_cookie = login_response.cookies.get('sessionid')
        self.assertIsNotNone(session_cookie)
        self.assertTrue(session_cookie['httponly'])
