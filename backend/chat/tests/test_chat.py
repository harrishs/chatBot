import json
import os
from typing import List
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
from chat.utils.jira import extract_plain_text_from_adf, fetch_jira_issues, ingest_jira_issue
from chat.utils.rag import _metadata_from_document
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
            remote_id="c-1",
        )

    @patch("chat.utils.embeddings.embed_text", return_value=[0.1] * 1536)
    def test_ingest_jira_issue_uses_canonical_sources(self, mock_embed_text):
        resolved_at = timezone.now().replace(microsecond=0)
        self.issue.status = "Done"
        self.issue.status_category = "Done"
        self.issue.status_category_changed_at = resolved_at
        self.issue.assignee = "Casey Completed"
        self.issue.resolution = "Fixed"
        self.issue.resolution_date = resolved_at
        self.issue.save(
            update_fields=[
                "status",
                "status_category",
                "status_category_changed_at",
                "assignee",
                "resolution",
                "resolution_date",
            ]
        )

        ingest_jira_issue(
            company=self.company,
            chatbot=self.chatbot,
            issue=self.issue,
            comments=[self.comment],
        )

        documents = Document.objects.filter(company=self.company, chatbot=self.chatbot)

        self.assertEqual(documents.count(), 2)
        sources = {(doc.source, doc.source_id) for doc in documents}
        expected_comment_id = f"{self.issue.issue_key}#comment#{self.comment.remote_id}"
        self.assertSetEqual(
            sources,
            {
                ("jira_issue", self.issue.issue_key),
                ("jira_comment", expected_comment_id),
            },
        )

        issue_document = documents.get(source="jira_issue", source_id=self.issue.issue_key)
        self.assertIn("Issue details:", issue_document.content)
        self.assertIn("Status: Done", issue_document.content)
        self.assertIn("Status category: Done", issue_document.content)
        self.assertIn("Assignee: Casey Completed", issue_document.content)
        self.assertIn("Resolution: Fixed", issue_document.content)
        self.assertIn("Resolved at:", issue_document.content)
        self.assertIn(resolved_at.isoformat(), issue_document.content)
        self.assertIn("Completion summary: Issue completed and resolved.", issue_document.content)
        self.assertIn("Description:\nIssue description", issue_document.content)

        issue_embedding_payload = mock_embed_text.call_args_list[0].args[0]
        self.assertIn("Status: Done", issue_embedding_payload)
        self.assertIn("Resolution: Fixed", issue_embedding_payload)
        self.assertIn("Completion summary: Issue completed and resolved.", issue_embedding_payload)

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


    @patch("chat.utils.embeddings.embed_text")
    def test_completion_metadata_surfaces_completed_issues(self, mock_embed_text):
        def fake_embed(text: str) -> List[float]:
            vector = [0.0] * 1536
            lowered = text.lower()
            if "completed" in lowered or "resolved" in lowered or "status: done" in lowered:
                vector[0] = 1.0
            else:
                vector[1] = 1.0
            return vector

        mock_embed_text.side_effect = fake_embed

        resolved_at = timezone.now().replace(microsecond=0)
        self.issue.status = "Done"
        self.issue.status_category = "Done"
        self.issue.status_category_changed_at = resolved_at
        self.issue.assignee = "Casey Completed"
        self.issue.resolution = "Fixed"
        self.issue.resolution_date = resolved_at
        self.issue.save(
            update_fields=[
                "status",
                "status_category",
                "status_category_changed_at",
                "assignee",
                "resolution",
                "resolution_date",
            ]
        )

        ingest_jira_issue(
            company=self.company,
            chatbot=self.chatbot,
            issue=self.issue,
            comments=[self.comment],
        )

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="What was the last completed issue?",
            top_k=5,
        )

        self.assertGreaterEqual(len(results), 1)
        top_result = results[0]
        self.assertEqual(top_result["source"], "jira_issue")
        self.assertIn("Status: Done", top_result["content"])
        self.assertIn("Completion summary: Issue completed and resolved.", top_result["content"])
        self.assertIn(resolved_at.isoformat(), top_result["content"])
        self.assertTrue(mock_embed_text.called)


class JiraADFDescriptionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="ADF Co")
        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="ADF Bot",
        )
        self.credential = Credential.objects.create(
            company=self.company,
            name="ADF Cred",
            email="adf@example.com",
            _api_key="placeholder",
        )
        self.sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/ADF/boards/1",
            credential=self.credential,
        )

    @patch("chat.utils.embeddings.embed_text", return_value=[0.0] * 1536)
    @patch("chat.utils.jira.fetch_comments", return_value=[])
    @patch("chat.utils.jira.fetch_board_filter_jql", return_value=None)
    @patch("chat.utils.jira._log_request_response")
    @patch("chat.utils.jira.decrypt_api_key", return_value="test-token")
    def test_sync_pipeline_normalizes_adf_description(
        self,
        _mock_decrypt,
        mock_log_request,
        _mock_fetch_board_jql,
        _mock_fetch_comments,
        _mock_embed_text,
    ):
        class _MockResponse:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        adf_description = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "ADF plain text"},
                    ],
                }
            ],
        }
        plain_text = extract_plain_text_from_adf(adf_description)

        payload = {
            "issues": [
                {
                    "key": "ADF-1",
                    "fields": {
                        "summary": "ADF Issue",
                        "description": adf_description,
                        "status": {"name": "To Do"},
                        "created": "2024-01-01T00:00:00.000+0000",
                        "updated": "2024-01-01T01:00:00.000+0000",
                    },
                }
            ],
            "isLast": True,
            "total": 1,
            "maxResults": 50,
        }
        mock_log_request.return_value = _MockResponse(payload)

        processed, _, _ = fetch_jira_issues(self.sync)

        self.assertEqual(len(processed), 1)

        issue_obj, comments = processed[0]
        issue_obj.refresh_from_db()
        self.assertEqual(issue_obj.description, plain_text)

        ingest_jira_issue(
            company=self.company,
            chatbot=self.chatbot,
            issue=issue_obj,
            comments=comments,
        )

        issue_document = Document.objects.get(
            company=self.company,
            chatbot=self.chatbot,
            source="jira_issue",
            source_id=issue_obj.issue_key,
        )

        self.assertIn(plain_text, issue_document.content)


class RagMetadataSummaryTests(TestCase):
    def test_metadata_summary_includes_resolved_line(self):
        content_lines = [
            "Issue details:",
            "Line 2",
            "Line 3",
            "Line 4",
            "Line 5",
            "Line 6",
            "Line 7",
            "Line 8",
            "Background information continues.",
            "Resolved at: 2024-06-05T12:34:56Z",
            "Completion summary: Issue closed successfully.",
        ]
        document = {
            "id": 1,
            "source": "jira_issue",
            "source_id": "TEST-123",
            "source_display": "TEST-123",
            "content": "\n".join(content_lines),
        }

        metadata = _metadata_from_document(document)

        summary = metadata.get("summary", "")
        self.assertIn("Resolved at: 2024-06-05T12:34:56Z", summary)
        self.assertIn("Completion summary: Issue closed successfully.", summary)


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

    @patch("chat.views.search_documents")
    def test_query_documents_rejects_non_numeric_top_k(self, mock_search_documents):
        response = self.client.post(
            self.query_url,
            {"query": "Hello", "top_k": "abc"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"top_k": ["Must be an integer greater than or equal to 1."]},
        )
        mock_search_documents.assert_not_called()

    @patch("chat.views.search_documents")
    def test_query_documents_rejects_non_positive_top_k(self, mock_search_documents):
        response = self.client.post(
            self.query_url,
            {"query": "Hello", "top_k": 0},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"top_k": ["Must be an integer greater than or equal to 1."]},
        )
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

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_jira_sync_create_with_foreign_chatbot_returns_404(self):
        foreign_chatbot = ChatBotInstance.objects.create(
            company=self.other_company,
            name="Other Bot",
        )
        url = f"/api/chatBots/{foreign_chatbot.id}/jiraSyncs/"
        payload = {
            'board_url': 'https://example.atlassian.net',
            'credential_id': self.tenant_credential.id,
            'sync_interval': JiraSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_confluence_sync_create_rejects_foreign_credential(self):
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/"
        payload = {
            'space_url': 'https://example.atlassian.net/wiki',
            'credential_id': self.foreign_credential.id,
            'sync_interval': ConfluenceSync.SYNC_INTERVAL_CHOICES[0][0],
        }

        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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

    def test_jira_sync_with_non_numeric_chatbot_pk_returns_400(self):
        response = self.client.get("/api/chatBots/abc/jiraSyncs/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('chatbot', response.data)

    def test_confluence_sync_with_non_numeric_chatbot_pk_returns_400(self):
        response = self.client.get("/api/chatBots/abc/confluenceSyncs/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('chatbot', response.data)

    def test_git_repo_sync_with_non_numeric_chatbot_pk_returns_400(self):
        response = self.client.get("/api/chatBots/abc/gitRepoSyncs/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('chatbot', response.data)


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

    def test_admin_cannot_update_other_company(self):
        self.client.force_authenticate(user=self.admin_user)

        url = reverse("company-detail", args=[self.company_two.id])
        response = self.client.patch(url, {"name": "Updated"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.company_two.refresh_from_db()
        self.assertEqual(self.company_two.name, "Company Two")


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
