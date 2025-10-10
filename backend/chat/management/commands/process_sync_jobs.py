import logging
import time
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from chat.models import SyncJob, SyncStatusMixin, JiraSync, ConfluenceSync, GitRepoSync
from chat.tasks import run_jira_sync, run_confluence_sync, run_git_repo_sync


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process queued Jira, Confluence, and Git repository sync jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--sleep', type=int, default=5, help='Seconds to wait between polling for jobs.')
        parser.add_argument('--once', action='store_true', help='Process a single available job and exit.')

    def handle(self, *args, **options):
        sleep_seconds: int = options['sleep']
        run_once: bool = options['once']

        self.stdout.write(self.style.SUCCESS('Sync job worker started.'))
        while True:
            job = self._dequeue_job()
            if not job:
                if run_once:
                    break
                time.sleep(sleep_seconds)
                continue

            self._process_job(job)
            if run_once:
                break

    def _dequeue_job(self) -> Optional[SyncJob]:
        with transaction.atomic():
            job = (
                SyncJob.objects.select_for_update(skip_locked=True)
                .filter(status=SyncStatusMixin.Status.QUEUED)
                .order_by('enqueued_at')
                .first()
            )
            if not job:
                return None

            job.status = SyncStatusMixin.Status.RUNNING
            job.status_message = 'Processing sync job.'
            job.started_at = timezone.now()
            job.save(update_fields=['status', 'status_message', 'started_at'])
            return job

    def _process_job(self, job: SyncJob) -> None:
        job_id = str(job.pk)
        success_message: Optional[str] = None

        try:
            if job.sync_type == SyncJob.JobType.JIRA:
                issues, docs = run_jira_sync(job.sync_id, job_id=job_id)
                success_message = f'Processed {issues} Jira issues ({docs} documents ingested).'
            elif job.sync_type == SyncJob.JobType.CONFLUENCE:
                pages, docs = run_confluence_sync(job.sync_id, job_id=job_id)
                success_message = f'Processed {pages} Confluence pages ({docs} documents ingested).'
            elif job.sync_type == SyncJob.JobType.GIT:
                files, docs = run_git_repo_sync(job.sync_id, job_id=job_id)
                success_message = f'Processed {files} repository files ({docs} documents ingested).'
            else:
                raise ValueError(f'Unknown job type: {job.sync_type}')
        except Exception as exc:
            logger.exception('Sync job %s failed', job.pk)
            sync_status_message = self._load_sync_status_message(job)
            job.status = SyncStatusMixin.Status.FAILED
            job.status_message = sync_status_message or str(exc)
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'status_message', 'finished_at'])
            return

        job.status = SyncStatusMixin.Status.SUCCEEDED
        job.status_message = success_message or 'Sync completed successfully.'
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'status_message', 'finished_at'])

    def _load_sync_status_message(self, job: SyncJob) -> Optional[str]:
        model = None
        if job.sync_type == SyncJob.JobType.JIRA:
            model = JiraSync
        elif job.sync_type == SyncJob.JobType.CONFLUENCE:
            model = ConfluenceSync
        elif job.sync_type == SyncJob.JobType.GIT:
            model = GitRepoSync

        if not model:
            return None

        try:
            sync = model.objects.get(pk=job.sync_id)
        except model.DoesNotExist:  # type: ignore[attr-defined]
            return None

        return getattr(sync, 'sync_status_message', None)
