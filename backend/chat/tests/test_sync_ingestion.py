from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from chat.models import (
    ChatBotInstance,
    Company,
    ConfluenceSync,
    Document,
    GitCredential,
    GitRepoSync,
    JiraSync,
    SyncJob,
    SyncStatusMixin,
)
from chat.tasks import SyncRunResult, run_confluence_sync, run_git_repo_sync, run_jira_sync


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

    @patch("chat.management.commands.process_sync_jobs.run_jira_sync")
    @patch("chat.utils.embeddings.embed_text", return_value=[0.1] * 1536)
    def test_jira_sync_now_creates_documents(self, mock_embed_text, mock_run_jira_sync):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )

        def fake_run(sync_id, job_id=None):
            self.assertEqual(sync_id, sync.id)
            sync_obj = JiraSync.objects.get(pk=sync_id)
            issue_embedding = mock_embed_text("jira-issue")
            comment_embedding = mock_embed_text("jira-comment")
            Document.objects.create(
                company=sync_obj.chatBot.company,
                chatbot=sync_obj.chatBot,
                source="jira_issue",
                source_id="TEST-1",
                content="Sample issue",
                embedding=issue_embedding,
            )
            Document.objects.create(
                company=sync_obj.chatBot.company,
                chatbot=sync_obj.chatBot,
                source="jira_comment",
                source_id="TEST-1-comment",
                content="A helpful comment",
                embedding=comment_embedding,
            )
            sync_obj.sync_status = JiraSync.Status.SUCCEEDED
            sync_obj.sync_status_message = (
                "Processed 1 issues and ingested 2 documents. Deleted 0 issues and 0 comments."
            )
            sync_obj.last_sync_time = timezone.now()
            sync_obj.update_next_sync_at(reference_time=sync_obj.last_sync_time)
            if job_id:
                sync_obj.current_job_id = job_id
            sync_obj.save(
                update_fields=[
                    "sync_status",
                    "sync_status_message",
                    "last_sync_time",
                    "next_sync_at",
                    "current_job_id",
                ]
            )
            return SyncRunResult(processed=1, documents=2, deleted={"issues": 0, "comments": 0})

        mock_run_jira_sync.side_effect = fake_run

        url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/sync_now/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("job_id", response.data)
        job_id = response.data["job_id"]

        call_command("process_sync_jobs", once=True)

        mock_run_jira_sync.assert_called_once_with(sync.id, job_id=str(job_id))
        self.assertEqual(Document.objects.count(), 2)

        job = SyncJob.objects.get(pk=int(job_id))
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            job.status_message,
            "Processed 1 Jira issues (2 documents ingested, 0 issues deleted, 0 comments deleted).",
        )

        sync.refresh_from_db()
        self.assertEqual(sync.sync_status, JiraSync.Status.SUCCEEDED)
        self.assertEqual(
            sync.sync_status_message,
            "Processed 1 issues and ingested 2 documents. Deleted 0 issues and 0 comments.",
        )
        self.assertIsNotNone(sync.last_sync_time)

        status_url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/status/"
        status_response = self.client.get(status_url)
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["job_id"], str(job_id))
        self.assertEqual(status_response.data["status"], JiraSync.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["message"],
            "Processed 1 issues and ingested 2 documents. Deleted 0 issues and 0 comments.",
        )
        self.assertEqual(status_response.data["job_status"], SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["job_message"],
            "Processed 1 Jira issues (2 documents ingested, 0 issues deleted, 0 comments deleted).",
        )
        self.assertEqual(mock_embed_text.call_count, 2)

    @patch("chat.management.commands.process_sync_jobs.run_confluence_sync")
    @patch("chat.utils.embeddings.embed_text", return_value=[0.2] * 1536)
    def test_confluence_sync_now_creates_documents(self, mock_embed_text, mock_run_confluence_sync):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki/spaces/CONF/pages/1",
        )

        def fake_run(sync_id, job_id=None):
            self.assertEqual(sync_id, sync.id)
            sync_obj = ConfluenceSync.objects.get(pk=sync_id)
            embedding = mock_embed_text("confluence-page")
            Document.objects.create(
                company=sync_obj.chatBot.company,
                chatbot=sync_obj.chatBot,
                source="confluence",
                source_id="CONF-1",
                content="Welcome to the space",
                embedding=embedding,
            )
            sync_obj.sync_status = ConfluenceSync.Status.SUCCEEDED
            sync_obj.sync_status_message = (
                "Processed 1 pages and ingested 1 documents. Deleted 0 pages."
            )
            sync_obj.last_sync_time = timezone.now()
            sync_obj.update_next_sync_at(reference_time=sync_obj.last_sync_time)
            if job_id:
                sync_obj.current_job_id = job_id
            sync_obj.save(
                update_fields=[
                    "sync_status",
                    "sync_status_message",
                    "last_sync_time",
                    "next_sync_at",
                    "current_job_id",
                ]
            )
            return SyncRunResult(processed=1, documents=1, deleted={"pages": 0})

        mock_run_confluence_sync.side_effect = fake_run

        url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/confluenceSyncs/{sync.pk}/sync_now/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("job_id", response.data)
        job_id = response.data["job_id"]

        call_command("process_sync_jobs", once=True)

        mock_run_confluence_sync.assert_called_once_with(sync.id, job_id=str(job_id))
        self.assertEqual(Document.objects.count(), 1)

        job = SyncJob.objects.get(pk=int(job_id))
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            job.status_message,
            "Processed 1 Confluence pages (1 documents ingested, 0 pages deleted).",
        )

        sync.refresh_from_db()
        self.assertEqual(sync.sync_status, ConfluenceSync.Status.SUCCEEDED)
        self.assertEqual(
            sync.sync_status_message,
            "Processed 1 pages and ingested 1 documents. Deleted 0 pages.",
        )
        self.assertIsNotNone(sync.last_sync_time)

        status_url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/confluenceSyncs/{sync.pk}/status/"
        status_response = self.client.get(status_url)
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["job_id"], str(job_id))
        self.assertEqual(status_response.data["status"], ConfluenceSync.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["message"],
            "Processed 1 pages and ingested 1 documents. Deleted 0 pages.",
        )
        self.assertEqual(status_response.data["job_status"], SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["job_message"],
            "Processed 1 Confluence pages (1 documents ingested, 0 pages deleted).",
        )
        self.assertEqual(mock_embed_text.call_count, 1)

    @patch("chat.management.commands.process_sync_jobs.run_git_repo_sync")
    @patch("chat.utils.embeddings.embed_text", return_value=[0.3] * 1536)
    def test_github_sync_now_creates_documents(self, mock_embed_text, mock_run_git_repo_sync):
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

        url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/gitRepoSyncs/{sync.pk}/sync_now/"
        response = self.client.post(url)

        def fake_run(sync_id, job_id=None):
            self.assertEqual(sync_id, sync.id)
            sync_obj = GitRepoSync.objects.get(pk=sync_id)
            embedding = mock_embed_text("github-file")
            Document.objects.create(
                company=sync_obj.chatBot.company,
                chatbot=sync_obj.chatBot,
                source="github",
                source_id="README.md",
                content="Hello world",
                embedding=embedding,
            )
            sync_obj.sync_status = GitRepoSync.Status.SUCCEEDED
            sync_obj.sync_status_message = (
                "Processed 1 files and ingested 1 documents. Deleted 0 files."
            )
            sync_obj.last_sync_time = timezone.now()
            sync_obj.update_next_sync_at(reference_time=sync_obj.last_sync_time)
            if job_id:
                sync_obj.current_job_id = job_id
            sync_obj.save(
                update_fields=[
                    "sync_status",
                    "sync_status_message",
                    "last_sync_time",
                    "next_sync_at",
                    "current_job_id",
                ]
            )
            return SyncRunResult(processed=1, documents=1, deleted={"files": 0})

        mock_run_git_repo_sync.side_effect = fake_run

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("job_id", response.data)
        job_id = response.data["job_id"]

        call_command("process_sync_jobs", once=True)

        mock_run_git_repo_sync.assert_called_once_with(sync.id, job_id=str(job_id))
        self.assertEqual(Document.objects.count(), 1)

        job = SyncJob.objects.get(pk=int(job_id))
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            job.status_message,
            "Processed 1 repository files (1 documents ingested, 0 files deleted).",
        )

        sync.refresh_from_db()
        self.assertEqual(sync.sync_status, GitRepoSync.Status.SUCCEEDED)
        self.assertEqual(
            sync.sync_status_message,
            "Processed 1 files and ingested 1 documents. Deleted 0 files.",
        )
        self.assertIsNotNone(sync.last_sync_time)

        status_url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/gitRepoSyncs/{sync.pk}/status/"
        status_response = self.client.get(status_url)
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["job_id"], str(job_id))
        self.assertEqual(status_response.data["status"], GitRepoSync.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["message"],
            "Processed 1 files and ingested 1 documents. Deleted 0 files.",
        )
        self.assertEqual(status_response.data["job_status"], SyncStatusMixin.Status.SUCCEEDED)
        self.assertEqual(
            status_response.data["job_message"],
            "Processed 1 repository files (1 documents ingested, 0 files deleted).",
        )
        self.assertEqual(mock_embed_text.call_count, 1)

    def test_jira_sync_now_logs_errors(self):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )

        url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/sync_now/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job_id = response.data["job_id"]

        def failing_run(sync_id, job_id=None):
            self.assertEqual(sync_id, sync.id)
            sync_obj = JiraSync.objects.get(pk=sync_id)
            sync_obj.sync_status = JiraSync.Status.FAILED
            sync_obj.sync_status_message = "Failed to sync Jira."
            if job_id:
                sync_obj.current_job_id = job_id
            sync_obj.save(
                update_fields=["sync_status", "sync_status_message", "current_job_id"],
            )
            raise RuntimeError("boom")

        with patch(
            "chat.management.commands.process_sync_jobs.run_jira_sync",
            side_effect=failing_run,
        ) as mock_run:
            call_command("process_sync_jobs", once=True)

        mock_run.assert_called_once_with(sync.id, job_id=str(job_id))

        job = SyncJob.objects.get(pk=int(job_id))
        self.assertEqual(job.status, SyncStatusMixin.Status.FAILED)
        self.assertEqual(job.status_message, "Failed to sync Jira.")

        sync.refresh_from_db()
        self.assertEqual(sync.sync_status, JiraSync.Status.FAILED)
        self.assertEqual(sync.sync_status_message, "Failed to sync Jira.")

        status_url = f"{self.api_prefix}/chatBots/{self.chatbot.pk}/jiraSyncs/{sync.pk}/status/"
        status_response = self.client.get(status_url)
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["status"], JiraSync.Status.FAILED)
        self.assertEqual(status_response.data["message"], "Failed to sync Jira.")
        self.assertEqual(status_response.data["job_status"], SyncStatusMixin.Status.FAILED)
        self.assertEqual(status_response.data["job_message"], "Failed to sync Jira.")
        self.assertEqual(Document.objects.count(), 0)

    @patch("chat.tasks.ingest_jira_issue", return_value=[])
    @patch("chat.tasks.fetch_jira_issues", return_value=([], set(), {}))
    def test_jira_sync_cleanup_removes_missing_content(self, mock_fetch, mock_ingest):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
        )

        issue = sync.issues.create(
            issue_key="TEST-1",
            summary="Old issue",
            description="Desc",
            status="Done",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        comment = issue.comments.create(
            author="Alice",
            content="Hello",
            created_at=timezone.now(),
            remote_id="c-1",
        )

        Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="jira_issue",
            source_id=issue.issue_key,
            content="Old issue",
            embedding=[0.0] * 1536,
        )
        Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="jira_comment",
            source_id=f"{issue.issue_key}_comment_{comment.pk}",
            content="Hello",
            embedding=[0.0] * 1536,
        )

        result = run_jira_sync(sync.id)

        self.assertEqual(result.deleted["issues"], 1)
        self.assertEqual(result.deleted["comments"], 1)
        self.assertFalse(sync.issues.exists())
        self.assertEqual(Document.objects.count(), 0)

    @patch("chat.tasks.ingest_confluence_pages", return_value=0)
    @patch("chat.tasks.fetch_confluence_pages", return_value=([], set()))
    def test_confluence_sync_cleanup_removes_missing_pages(self, mock_fetch, mock_ingest):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki/spaces/CONF/pages/1",
        )

        page = sync.pages.create(
            remote_id="p-1",
            title="Old page",
            content="Body",
            url="https://example.atlassian.net/wiki/p-1",
            last_updated=timezone.now(),
        )

        Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id=page.pk,
            content="Body",
            embedding=[0.0] * 1536,
        )

        result = run_confluence_sync(sync.id)

        self.assertEqual(result.deleted["pages"], 1)
        self.assertFalse(sync.pages.exists())
        self.assertEqual(Document.objects.count(), 0)

    @patch("chat.tasks.run_github_sync", return_value=(0, 0, set()))
    def test_git_sync_cleanup_removes_missing_files(self, mock_run):
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

        repo_file = sync.files.create(
            path="README.md",
            sha="abc",
            size=10,
            url="https://github.com/octocat/hello-world/blob/main/README.md",
            content="Hello",
            last_updated=timezone.now(),
        )

        Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="github",
            source_id=str(repo_file.pk),
            content="Hello",
            embedding=[0.0] * 1536,
        )

        result = run_git_repo_sync(sync.id)

        self.assertEqual(result.deleted["files"], 1)
        self.assertFalse(sync.files.exists())
        self.assertEqual(Document.objects.count(), 0)
