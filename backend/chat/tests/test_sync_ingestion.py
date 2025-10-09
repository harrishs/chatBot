from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from chat.models import (
    ChatBotInstance,
    Company,
    ConfluencePage,
    ConfluenceSync,
    Document,
    GitCredential,
    GitRepoSync,
    JiraComment,
    JiraIssue,
    JiraSync,
)


User = get_user_model()


class SyncIngestionTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Sync Co")
        self.user = User.objects.create_user(
            username="sync-user",
            password="pass1234",
            company=self.company,
            is_staff=True,
        )
        self.client.force_authenticate(self.user)
        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="SyncBot",
        )
        self.api_prefix = "/api"

    @patch("chat.utils.embeddings.embed_text", return_value=[0.1] * 1536)
    def test_jira_sync_now_creates_documents(self, mock_embed_text):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )

        def fake_fetch(fetch_sync):
            issue = JiraIssue.objects.create(
                sync=fetch_sync,
                issue_key="TEST-1",
                summary="Sample issue",
                description="Issue description",
                status="To Do",
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )
            comment = JiraComment.objects.create(
                issue=issue,
                author="Commenter",
                content="A helpful comment",
                created_at=timezone.now(),
            )
            return [(issue, [comment])]

        with patch("chat.views.fetch_jira_issues", side_effect=fake_fetch):
            url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/sync_now/"
            response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_ingested"], 2)
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(mock_embed_text.call_count, 2)

    @patch("chat.utils.embeddings.embed_text", return_value=[0.2] * 1536)
    def test_confluence_sync_now_creates_documents(self, mock_embed_text):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki/spaces/CONF/pages/1",
        )

        def fake_fetch(fetch_sync):
            page = ConfluencePage.objects.create(
                sync=fetch_sync,
                title="Welcome",
                content="Welcome to the space",
                url="https://example.atlassian.net/wiki/spaces/CONF/pages/1",
                last_updated=timezone.now(),
            )
            return [page]

        with patch("chat.views.fetch_confluence_pages", side_effect=fake_fetch):
            url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/confluenceSyncs/{sync.pk}/sync_now/"
            response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_ingested"], 1)
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(mock_embed_text.call_count, 1)

    @patch("chat.utils.github._get_last_commit_date")
    @patch("chat.utils.github._get_blob")
    @patch("chat.utils.github._list_tree")
    @patch("chat.utils.github.decrypt_api_key", return_value="token")
    @patch("chat.utils.embeddings.embed_text", return_value=[0.3] * 1536)
    def test_github_sync_now_creates_documents(
        self,
        mock_embed_text,
        mock_decrypt,
        mock_list_tree,
        mock_get_blob,
        mock_get_last_commit,
    ):
        credential = GitCredential(
            company=self.company,
            name="GitHub",
            github_username="octocat",
        )
        credential.token = "token"
        credential.save()

        sync = GitRepoSync.objects.create(
            chatBot=self.chatbot,
            credential=credential,
            repo_full_name="octocat/hello-world",
            branch="main",
        )

        mock_list_tree.return_value = [{"type": "blob", "path": "README.md", "sha": "abc123"}]
        mock_get_blob.return_value = b"Hello world"
        mock_get_last_commit.return_value = timezone.now()

        url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/gitRepoSyncs/{sync.pk}/sync_now/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_ingested"], 1)
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(mock_embed_text.call_count, 1)

    def test_jira_sync_now_logs_errors(self):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )

        with patch("chat.views.fetch_jira_issues", side_effect=RuntimeError("boom")):
            with self.assertLogs("chat.views", level="ERROR") as logs:
                url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/sync_now/"
                response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["detail"], "Failed to sync Jira.")
        self.assertTrue(any("Failed to sync Jira" in message for message in logs.output))
