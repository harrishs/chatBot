from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from chat.models import (
    ChatBotInstance,
    Company,
    ConfluenceSync,
    GitCredential,
    GitRepoSync,
    JiraSync,
    SyncJob,
    SyncStatusMixin,
)
from chat.tasks import SyncRunResult, _set_status


class SyncSchedulingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Scheduler Co")
        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="SchedulerBot",
        )

    @patch("chat.management.commands.process_sync_jobs.run_jira_sync")
    def test_daily_sync_enqueued_automatically(self, mock_run_jira_sync):
        past = timezone.now() - timedelta(days=2)
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/board/1",
            last_sync_time=past,
            sync_interval="daily",
        )
        sync.update_next_sync_at()
        sync.save(update_fields=["last_sync_time", "next_sync_at"])

        def fake_run(sync_id, job_id=None):
            sync_obj = JiraSync.objects.get(pk=sync_id)
            _set_status(
                sync_obj,
                JiraSync.Status.SUCCEEDED,
                "Automated daily sync complete.",
                update_last_sync_time=True,
                job_id=job_id,
            )
            return SyncRunResult(processed=0, documents=0, deleted={"issues": 0, "comments": 0})

        mock_run_jira_sync.side_effect = fake_run

        call_command("process_sync_jobs", once=True)

        sync.refresh_from_db()
        jobs = SyncJob.objects.filter(sync_type=SyncJob.JobType.JIRA, sync_id=sync.id)
        self.assertEqual(jobs.count(), 1)
        job = jobs.first()
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertGreater(sync.next_sync_at, timezone.now())
        mock_run_jira_sync.assert_called_once_with(sync.id, job_id=str(job.pk))

        # Running the worker again should not enqueue a duplicate job while the
        # next run is scheduled in the future.
        call_command("process_sync_jobs", once=True)
        self.assertEqual(
            SyncJob.objects.filter(sync_type=SyncJob.JobType.JIRA, sync_id=sync.id).count(),
            1,
        )

    @patch("chat.management.commands.process_sync_jobs.run_confluence_sync")
    def test_weekly_sync_enqueued_when_due(self, mock_run_confluence_sync):
        past = timezone.now() - timedelta(days=8)
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki/spaces/CONF",
            last_sync_time=past,
            sync_interval="weekly",
        )
        sync.update_next_sync_at()
        sync.save(update_fields=["last_sync_time", "next_sync_at"])

        def fake_run(sync_id, job_id=None):
            sync_obj = ConfluenceSync.objects.get(pk=sync_id)
            _set_status(
                sync_obj,
                ConfluenceSync.Status.SUCCEEDED,
                "Automated weekly sync complete.",
                update_last_sync_time=True,
                job_id=job_id,
            )
            return SyncRunResult(processed=0, documents=0, deleted={"pages": 0})

        mock_run_confluence_sync.side_effect = fake_run

        call_command("process_sync_jobs", once=True)

        sync.refresh_from_db()
        job = SyncJob.objects.get(sync_type=SyncJob.JobType.CONFLUENCE, sync_id=sync.id)
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertGreater(sync.next_sync_at, sync.last_sync_time)
        self.assertLessEqual(
            sync.next_sync_at - sync.last_sync_time,
            timedelta(days=7, minutes=1),
        )
        mock_run_confluence_sync.assert_called_once_with(sync.id, job_id=str(job.pk))

    @patch("chat.management.commands.process_sync_jobs.run_git_repo_sync")
    def test_initial_sync_without_last_run_is_enqueued(self, mock_run_git_repo_sync):
        credential = GitCredential.objects.create(
            company=self.company,
            name="Token",
            github_username="bot",
            _token="encrypted",
        )
        sync = GitRepoSync.objects.create(
            chatBot=self.chatbot,
            credential=credential,
            repo_full_name="example/repo",
            branch="main",
            sync_interval="daily",
        )

        def fake_run(sync_id, job_id=None):
            sync_obj = GitRepoSync.objects.get(pk=sync_id)
            _set_status(
                sync_obj,
                GitRepoSync.Status.SUCCEEDED,
                "Initial sync complete.",
                update_last_sync_time=True,
                job_id=job_id,
            )
            return SyncRunResult(processed=0, documents=0, deleted={"files": 0})

        mock_run_git_repo_sync.side_effect = fake_run

        call_command("process_sync_jobs", once=True)

        sync.refresh_from_db()
        job = SyncJob.objects.get(sync_type=SyncJob.JobType.GIT, sync_id=sync.id)
        self.assertEqual(job.status, SyncStatusMixin.Status.SUCCEEDED)
        self.assertIsNotNone(sync.last_sync_time)
        self.assertGreater(sync.next_sync_at, sync.last_sync_time)
        mock_run_git_repo_sync.assert_called_once_with(sync.id, job_id=str(job.pk))
