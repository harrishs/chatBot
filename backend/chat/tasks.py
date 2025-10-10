import logging
from typing import Optional, Tuple

import requests
from django.utils import timezone

from chat.models import JiraSync, ConfluenceSync, GitRepoSync
from chat.utils.jira import fetch_jira_issues, ingest_jira_issue
from chat.utils.confluence import fetch_confluence_pages, ingest_confluence_pages
from chat.utils.github import run_github_sync


logger = logging.getLogger(__name__)


def _set_status(sync, status, message, update_last_sync_time=False, job_id: Optional[str] = None):
    update_kwargs = {
        'sync_status': status,
        'sync_status_message': message,
    }
    fields_to_set = ['sync_status', 'sync_status_message']

    if update_last_sync_time:
        now = timezone.now()
        update_kwargs['last_sync_time'] = now
        fields_to_set.append('last_sync_time')
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


def run_jira_sync(sync_id: int, job_id: Optional[str] = None) -> Tuple[int, int]:
    sync = JiraSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, JiraSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        issues_with_comments = fetch_jira_issues(sync)
        documents_created = 0
        for issue, comments in issues_with_comments:
            docs = ingest_jira_issue(
                company=sync.chatBot.company,
                chatbot=sync.chatBot,
                issue=issue,
                comments=comments,
            )
            documents_created += len(docs)
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

    _set_status(
        sync,
        JiraSync.Status.SUCCEEDED,
        f'Processed {len(issues_with_comments)} issues and ingested {documents_created} documents.',
        update_last_sync_time=True,
        job_id=job_id,
    )
    return len(issues_with_comments), documents_created


def run_confluence_sync(sync_id: int, job_id: Optional[str] = None) -> Tuple[int, int]:
    sync = ConfluenceSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, ConfluenceSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        pages = fetch_confluence_pages(sync)
        documents_created = ingest_confluence_pages(sync, pages=pages)
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

    _set_status(
        sync,
        ConfluenceSync.Status.SUCCEEDED,
        f'Processed {len(pages)} pages and ingested {documents_created} documents.',
        update_last_sync_time=True,
        job_id=job_id,
    )
    return len(pages), documents_created


def run_git_repo_sync(sync_id: int, job_id: Optional[str] = None) -> Tuple[int, int]:
    sync = GitRepoSync.objects.select_related('chatBot__company', 'credential').get(pk=sync_id)
    _set_status(sync, GitRepoSync.Status.RUNNING, 'Sync in progress.', job_id=job_id)

    try:
        files_processed, documents_ingested = run_github_sync(sync)
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

    _set_status(
        sync,
        GitRepoSync.Status.SUCCEEDED,
        f'Processed {files_processed} files and ingested {documents_ingested} documents.',
        update_last_sync_time=True,
        job_id=job_id,
    )
    return files_processed, documents_ingested
