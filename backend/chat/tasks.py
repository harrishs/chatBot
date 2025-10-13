import logging
from dataclasses import dataclass
from typing import Dict, Optional

import requests
from django.utils import timezone

from chat.models import JiraSync, ConfluenceSync, GitRepoSync
from chat.utils.jira import cleanup_removed_jira_content, fetch_jira_issues, ingest_jira_issue
from chat.utils.confluence import cleanup_removed_confluence_pages, fetch_confluence_pages, ingest_confluence_pages
from chat.utils.github import cleanup_removed_github_files, run_github_sync


logger = logging.getLogger(__name__)


@dataclass
class SyncRunResult:
    processed: int
    documents: int
    deleted: Dict[str, int]


def _set_status(sync, status, message, update_last_sync_time=False, job_id: Optional[str] = None):
    update_kwargs = {
        'sync_status': status,
        'sync_status_message': message,
    }
    fields_to_set = ['sync_status', 'sync_status_message']

    if update_last_sync_time:
        now = timezone.now()
        update_kwargs['last_sync_time'] = now
        next_sync_at = sync.update_next_sync_at(reference_time=now, assume_started=True)
        update_kwargs['next_sync_at'] = next_sync_at
        fields_to_set.append('last_sync_time')
        fields_to_set.append('next_sync_at')
    if job_id is not None:
        update_kwargs['current_job_id'] = job_id
        fields_to_set.append('current_job_id')

    queryset = type(sync).objects.filter(pk=sync.pk)
    if job_id is not None:
        queryset = queryset.filter(current_job_id=job_id)

    updated = queryset.update(**update_kwargs)
    if not updated:
        if job_id is not None:
            logger.debug(
                "Skipping status update for sync %s and job %s because the current job changed.",
                sync.pk,
                job_id,
            )
        return

    for field in fields_to_set:
        setattr(sync, field, update_kwargs[field])


def run_jira_sync(sync_id: int, job_id: Optional[str] = None) -> SyncRunResult:
    sync = JiraSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, JiraSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        issues_with_comments, remote_issue_keys, remote_comment_tokens = fetch_jira_issues(sync)
        documents_created = 0
        for issue, comments in issues_with_comments:
            docs = ingest_jira_issue(
                company=sync.chatBot.company,
                chatbot=sync.chatBot,
                issue=issue,
                comments=comments,
            )
            documents_created += len(docs)
        deleted_issues, deleted_comments = cleanup_removed_jira_content(
            sync,
            remote_issue_keys,
            remote_comment_tokens,
        )
    except requests.Timeout:
        message = 'Jira sync timed out while contacting the Jira API.'
        logger.exception("Jira sync timed out for sync %s", sync.pk)
        _set_status(sync, JiraSync.Status.FAILED, message, job_id=job_id)
        raise
    except requests.RequestException as exc:
        message = f'Jira sync failed due to a network error: {exc}'
        logger.exception("Jira sync failed due to network error for sync %s", sync.pk)
        _set_status(sync, JiraSync.Status.FAILED, message, job_id=job_id)
        raise
    except Exception:
        message = 'Failed to sync Jira.'
        logger.exception("Failed to sync Jira for sync %s", sync.pk)
        _set_status(sync, JiraSync.Status.FAILED, message, job_id=job_id)
        raise

    result = SyncRunResult(
        processed=len(issues_with_comments),
        documents=documents_created,
        deleted={
            "issues": deleted_issues,
            "comments": deleted_comments,
        },
    )

    message = (
        f'Processed {result.processed} issues and ingested {result.documents} documents. '
        f'Deleted {deleted_issues} issues and {deleted_comments} comments.'
    )
    _set_status(
        sync,
        JiraSync.Status.SUCCEEDED,
        message,
        update_last_sync_time=True,
        job_id=job_id,
    )
    return result


def run_confluence_sync(sync_id: int, job_id: Optional[str] = None) -> SyncRunResult:
    sync = ConfluenceSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, ConfluenceSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        pages, remote_ids = fetch_confluence_pages(sync)
        documents_created = ingest_confluence_pages(sync, pages=pages)
        deleted_pages = cleanup_removed_confluence_pages(sync, pages, remote_ids)
    except requests.Timeout:
        message = 'Confluence sync timed out while contacting the Confluence API.'
        logger.exception("Confluence sync timed out for sync %s", sync.pk)
        _set_status(sync, ConfluenceSync.Status.FAILED, message, job_id=job_id)
        raise
    except requests.RequestException as exc:
        message = f'Confluence sync failed due to a network error: {exc}'
        logger.exception("Confluence sync failed due to network error for sync %s", sync.pk)
        _set_status(sync, ConfluenceSync.Status.FAILED, message, job_id=job_id)
        raise
    except Exception:
        message = 'Failed to sync Confluence.'
        logger.exception("Failed to sync Confluence for sync %s", sync.pk)
        _set_status(sync, ConfluenceSync.Status.FAILED, message, job_id=job_id)
        raise

    result = SyncRunResult(
        processed=len(pages),
        documents=documents_created,
        deleted={"pages": deleted_pages},
    )

    message = (
        f'Processed {result.processed} pages and ingested {result.documents} documents. '
        f'Deleted {deleted_pages} pages.'
    )
    _set_status(
        sync,
        ConfluenceSync.Status.SUCCEEDED,
        message,
        update_last_sync_time=True,
        job_id=job_id,
    )
    return result


def run_git_repo_sync(sync_id: int, job_id: Optional[str] = None) -> SyncRunResult:
    sync = GitRepoSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, GitRepoSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        files_processed, documents_ingested, remote_paths = run_github_sync(sync)
        deleted_files = cleanup_removed_github_files(sync, remote_paths)
    except requests.Timeout:
        message = 'GitHub sync timed out while contacting the GitHub API.'
        logger.exception("GitHub sync timed out for sync %s", sync.pk)
        _set_status(sync, GitRepoSync.Status.FAILED, message, job_id=job_id)
        raise
    except requests.RequestException as exc:
        message = f'GitHub sync failed due to a network error: {exc}'
        logger.exception("GitHub sync failed due to network error for sync %s", sync.pk)
        _set_status(sync, GitRepoSync.Status.FAILED, message, job_id=job_id)
        raise
    except Exception:
        message = 'Failed to sync GitHub.'
        logger.exception("Failed to sync GitHub for sync %s", sync.pk)
        _set_status(sync, GitRepoSync.Status.FAILED, message, job_id=job_id)
        raise

    result = SyncRunResult(
        processed=files_processed,
        documents=documents_ingested,
        deleted={"files": deleted_files},
    )

    message = (
        f'Processed {result.processed} files and ingested {result.documents} documents. '
        f'Deleted {deleted_files} files.'
    )
    _set_status(
        sync,
        GitRepoSync.Status.SUCCEEDED,
        message,
        update_last_sync_time=True,
        job_id=job_id,
    )
    return result
