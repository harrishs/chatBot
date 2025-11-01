from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from chat.models import (
    ChatBotInstance,
    Company,
    ConfluenceSync,
    Credential,
    GitCredential,
    GitRepoSync,
    JiraSync,
    SyncStatusMixin,
)


class ChatBotSyncSummaryAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="Tenant A")
        self.user = User.objects.create_user(
            username="tenant-user",
            email="tenant@example.com",
            password="password123",
            company=self.company,
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Support Bot",
        )
        self.credential = Credential.objects.create(
            company=self.company,
            name="Tenant Credential",
            email="tenant@example.com",
            _api_key="dummy",
        )
        self.git_credential = GitCredential.objects.create(
            company=self.company,
            name="Repo Credential",
            github_username="bot",
            _token="dummy",
        )

    def test_sync_summary_includes_all_sources(self):
        now = timezone.now()
        JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net",
            credential=self.credential,
            last_sync_time=now - timedelta(days=1),
            sync_status=SyncStatusMixin.Status.SUCCEEDED,
        )
        confluence_sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki",
            credential=self.credential,
            last_sync_time=now - timedelta(hours=2),
            sync_status=SyncStatusMixin.Status.FAILED,
            sync_status_message="Failed to fetch pages",
        )
        git_sync = GitRepoSync.objects.create(
            chatBot=self.chatbot,
            credential=self.git_credential,
            repo_full_name="org/repo",
            branch="main",
            next_sync_at=now + timedelta(hours=3),
            sync_status=SyncStatusMixin.Status.QUEUED,
        )

        response = self.client.get(f"/api/chatBots/{self.chatbot.id}/sync-summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["total_syncs"], 3)
        self.assertEqual(data["running_syncs"], 1)
        self.assertEqual(data["failing_syncs"], 1)
        self.assertEqual(data["breakdown"]["jira"]["total"], 1)
        self.assertEqual(data["breakdown"]["confluence"]["failing"], 1)
        self.assertEqual(data["breakdown"]["git"]["running"], 1)

        self.assertEqual(data["latest_run"]["type"], "confluence")
        self.assertEqual(data["latest_run"]["id"], confluence_sync.id)
        self.assertTrue(data["latest_run"]["timestamp"].endswith("Z"))

        self.assertEqual(data["next_scheduled"]["id"], git_sync.id)
        self.assertTrue(data["next_scheduled"]["timestamp"].endswith("Z"))

        self.assertEqual(data["last_failure"]["id"], confluence_sync.id)
        self.assertEqual(data["last_failure"]["message"], "Failed to fetch pages")

    def test_summary_respects_company_boundaries(self):
        other_company = Company.objects.create(name="Tenant B")
        foreign_chatbot = ChatBotInstance.objects.create(
            company=other_company,
            name="Other Bot",
        )

        response = self.client.get(f"/api/chatBots/{foreign_chatbot.id}/sync-summary/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
