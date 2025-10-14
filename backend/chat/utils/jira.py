import json
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from chat.encryption import decrypt_api_key
from urllib.parse import urlparse
from django.db.models import Q

from chat.models import Document, JiraIssue, JiraComment, JiraSync
from chat.utils.embeddings import save_document


logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = (5, 30)


_SENSITIVE_SUBSTRINGS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


def _format_context(context: Optional[Mapping[str, Any]]) -> str:
    if not context:
        return ""
    parts = [f"{key}={value}" for key, value in context.items() if value is not None]
    if not parts:
        return ""
    return "[" + " ".join(parts) + "] "


def _sanitize_string(value: str) -> str:
    lower_value = value.lower()
    if any(token in lower_value for token in _SENSITIVE_SUBSTRINGS):
        return "***REDACTED***"
    return value


def _sanitize_for_logging(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, Mapping):
        redacted: MutableMapping[Any, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and any(token in key.lower() for token in _SENSITIVE_SUBSTRINGS):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _sanitize_for_logging(value)
        return redacted
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        return [_sanitize_for_logging(item) for item in data]
    if isinstance(data, (bytes, bytearray)):
        return "<binary>"
    if isinstance(data, str):
        return _sanitize_string(data)
    return data


def _format_for_logging(data: Any, *, max_length: int = 512) -> Any:
    sanitized = _sanitize_for_logging(data)
    if sanitized is None:
        return None
    if isinstance(sanitized, (dict, list)):
        try:
            serialized = json.dumps(sanitized, sort_keys=True)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            serialized = repr(sanitized)
    else:
        serialized = str(sanitized)
    if len(serialized) > max_length:
        return f"{serialized[:max_length]}...(truncated)"
    return serialized


def _log_request_response(
    method: str,
    url: str,
    *,
    request_func: Callable[[], requests.Response],
    params: Optional[Mapping[str, Any]] = None,
    json_body: Any = None,
    context: Optional[Mapping[str, Any]] = None,
    response_max_length: int = 512,
) -> requests.Response:
    context_str = _format_context(context)
    logger.debug(
        "Jira API %sRequest %s %s params=%s json=%s",
        context_str,
        method.upper(),
        url,
        _format_for_logging(params),
        _format_for_logging(json_body),
    )
    try:
        response = request_func()
    except Exception:
        logger.debug(
            "Jira API %sRequest %s %s failed before receiving a response",
            context_str,
            method.upper(),
            url,
        )
        raise

    logger.debug(
        "Jira API %sResponse %s %s status=%s body=%s",
        context_str,
        method.upper(),
        url,
        getattr(response, "status_code", "unknown"),
        _format_for_logging(response.text, max_length=response_max_length),
    )
    return response


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def extract_plain_text_from_adf(document: Union[dict, list, None]) -> str:
    """Return the concatenated plain text representation of an ADF document.

    Atlassian comments are provided using the Atlassian Document Format (ADF),
    which is a nested structure of nodes.  Each node can contain child nodes in
    the ``content`` key, and leaf nodes may define ``text`` or represent a hard
    line break.  The structure is permissive and nodes or keys may be missing, so
    the helper needs to be defensive and never raise when traversing the
    document.
    """

    def _maybe_add_newline(parts: List[str]) -> None:
        if not parts:
            return
        if not parts[-1].endswith("\n"):
            parts.append("\n")

    def _walk(node: Union[dict, list, None], parts: List[str]) -> None:
        if node is None:
            return

        if isinstance(node, list):
            for child in node:
                _walk(child, parts)
            return

        if not isinstance(node, dict):
            return

        node_type = node.get("type")

        if node_type == "text":
            text = node.get("text")
            if text:
                parts.append(text)
            return

        if node_type == "emoji":
            short_name = node.get("attrs", {}).get("shortName")
            if short_name:
                parts.append(short_name)
            return

        if node_type == "hardBreak":
            parts.append("\n")
            return

        content = node.get("content")
        if not content:
            return

        before_len = len(parts)
        for child in content:
            _walk(child, parts)

        if node_type in {"paragraph", "heading", "blockquote", "listItem"}:
            if len(parts) > before_len:
                _maybe_add_newline(parts)

    collected: List[str] = []
    _walk(document, collected)
    return "".join(collected).strip()

def extract_project_key(board_url):
    # Example: https://yourdomain.atlassian.net/jira/software/c/projects/CPG/boards/1
    # Extract 'CPG' between /projects/ and /boards/
    try:
        parts = board_url.split("/projects/")
        if len(parts) > 1:
            project_part = parts[1].split("/")[0]
            return project_part
    except Exception:
        logger.exception("Error extracting project key from Jira board URL")
    return ""  # fallback if parsing fails


def extract_board_id(board_url: str) -> str:
    try:
        parts = board_url.split("/boards/")
        if len(parts) > 1:
            board_part = parts[1].split("/")[0]
            board_id = board_part.split("?")[0]
            return board_id
    except Exception:
        logger.exception("Error extracting board id from Jira board URL")
    return ""


def fetch_board_filter_jql(base_url: str, board_id: str, auth, headers, sync: JiraSync) -> str | None:
    if not board_id:
        return None

    filter_id: str | int | None = None

    board_metadata_url = f"{base_url}/rest/agile/1.0/board/{board_id}"
    try:
        response = _log_request_response(
            "GET",
            board_metadata_url,
            request_func=lambda: _SESSION.get(
                board_metadata_url,
                headers=headers,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
            ),
            context={
                "sync_id": sync.pk,
                "job_id": sync.current_job_id,
                "board_id": board_id,
            },
        )
        response.raise_for_status()
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to fetch Jira board metadata")
    else:
        try:
            payload = response.json() or {}
        except ValueError:
            logger.exception("Invalid JSON received from Jira board metadata")
        else:
            filter_id = payload.get("filterId")
            if not filter_id:
                filter_config = payload.get("filter") or {}
                filter_id = filter_config.get("id")
            logger.debug(
                "Sync %s (job=%s): Board metadata filter_id=%s",
                sync.pk,
                sync.current_job_id,
                filter_id,
            )

    filter_url: str | None = None
    if filter_id:
        filter_url = f"{base_url}/rest/api/3/filter/{filter_id}"
    else:
        config_url = f"{base_url}/rest/agile/1.0/board/{board_id}/configuration"
        try:
            response = _log_request_response(
                "GET",
                config_url,
                request_func=lambda: _SESSION.get(
                    config_url,
                    headers=headers,
                    auth=auth,
                    timeout=_REQUEST_TIMEOUT,
                ),
                context={
                    "sync_id": sync.pk,
                    "job_id": sync.current_job_id,
                    "board_id": board_id,
                },
            )
            response.raise_for_status()
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to fetch Jira board configuration")
            return None

        try:
            payload = response.json() or {}
        except ValueError:
            logger.exception("Invalid JSON received from Jira board configuration")
            return None

        filter_config = payload.get("filter") or {}
        filter_url = filter_config.get("self")
        if not filter_url:
            filter_id = filter_config.get("id")
            if filter_id:
                filter_url = f"{base_url}/rest/api/3/filter/{filter_id}"
        logger.debug(
            "Sync %s (job=%s): Board configuration filter_id=%s filter_url=%s",
            sync.pk,
            sync.current_job_id,
            filter_id,
            filter_url,
        )

    if not filter_url:
        return None

    try:
        filter_response = _log_request_response(
            "GET",
            filter_url,
            request_func=lambda: _SESSION.get(
                filter_url,
                headers=headers,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
            ),
            context={
                "sync_id": sync.pk,
                "job_id": sync.current_job_id,
                "board_id": board_id,
                "filter_id": filter_id,
            },
        )
        filter_response.raise_for_status()
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to fetch Jira board filter details")
        return None

    try:
        filter_payload = filter_response.json() or {}
    except ValueError:
        logger.exception("Invalid JSON received from Jira filter details")
        return None

    query = filter_payload.get("jql")
    if query:
        return query
    return None

def get_base_domain(board_url):
    parsed = urlparse(board_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def fetch_comments(base_url, issue_key, api_key, email, sync: JiraSync):
    url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    auth = requests.auth.HTTPBasicAuth(email, api_key)
    headers = {
        "Accept": "application/json"
    }

    comments: List[dict] = []
    start_at = 0
    max_results = 50

    while True:
        params = {"startAt": start_at, "maxResults": max_results}
        response = _log_request_response(
            "GET",
            url,
            request_func=lambda: _SESSION.get(
                url,
                headers=headers,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
                params=params,
            ),
            params=params,
            context={
                "sync_id": sync.pk,
                "job_id": sync.current_job_id,
                "issue_key": issue_key,
            },
        )
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("comments", []) or []
        if not batch:
            logger.warning(
                "Sync %s (job=%s) Issue %s: Empty Jira comments batch params=%s",
                sync.pk,
                sync.current_job_id,
                issue_key,
                params,
            )
            break

        logger.debug(
            "Sync %s (job=%s) Issue %s: Received %s comments (startAt=%s maxResults=%s)",
            sync.pk,
            sync.current_job_id,
            issue_key,
            len(batch),
            params["startAt"],
            params["maxResults"],
        )
        comments.extend(batch)

        if payload.get("isLast") is True:
            break

        batch_size = len(batch)
        total = payload.get("total")
        max_results = payload.get("maxResults", max_results) or max_results
        start_at = payload.get("startAt", start_at) + batch_size

        if total is not None and len(comments) >= total:
            break

        if batch_size < max_results:
            break

    return comments

def _delete_documents_for_source_ids(source: str, base_ids: Iterable[str]) -> int:
    deleted = 0
    for base_id in base_ids:
        if base_id is None:
            continue
        conditions = Q(source_id=str(base_id)) | Q(source_id__startswith=f"{base_id}_part_")
        deleted += Document.objects.filter(source=source).filter(conditions).delete()[0]
    return deleted


def fetch_jira_issues(sync: JiraSync) -> Tuple[List[Tuple[JiraIssue, List[JiraComment]]], Set[str], Dict[str, Set[str]]]:
    api_key = decrypt_api_key(sync.credential._api_key)
    project_key = extract_project_key(sync.board_url)
    board_id = extract_board_id(sync.board_url)
    base_url = get_base_domain(sync.board_url)
    email = sync.credential.email

    issue_url = f"{base_url}/rest/api/3/search/jql"
    auth = requests.auth.HTTPBasicAuth(email, api_key)
    headers = {
        "Accept": "application/json"
    }

    board_filter_jql = fetch_board_filter_jql(base_url, board_id, auth, headers, sync)
    jql_query = board_filter_jql or f"project={project_key}"
    logger.debug(
        "Sync %s (job=%s): Using JQL query '%s' (board_id=%s)",
        sync.pk,
        sync.current_job_id,
        jql_query,
        board_id,
    )

    issues: List[dict] = []
    max_results = 50
    next_page_token: str | None = None

    while True:
        body = {
            "jql": jql_query,
            "maxResults": max_results,
            "fields": [
                "summary",
                "description",
                "status",
                "created",
                "updated",
            ],
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token
        response = _log_request_response(
            "POST",
            issue_url,
            request_func=lambda: _SESSION.post(
                issue_url,
                headers=headers,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
                json=body,
            ),
            json_body=body,
            context={
                "sync_id": sync.pk,
                "job_id": sync.current_job_id,
                "board_id": board_id,
            },
        )
        response.raise_for_status()
        payload = response.json() or {}

        data = payload.get("data")
        page = data if isinstance(data, dict) else payload

        batch = page.get("issues", []) or []
        if not batch:
            logger.warning(
                "Sync %s (job=%s): Empty Jira issues batch jql='%s' maxResults=%s nextPageToken=%s",
                sync.pk,
                sync.current_job_id,
                jql_query,
                body["maxResults"],
                body.get("nextPageToken"),
            )
            break

        logger.debug(
            "Sync %s (job=%s): Received %s issues (maxResults=%s nextPageToken=%s)",
            sync.pk,
            sync.current_job_id,
            len(batch),
            page.get("maxResults", body["maxResults"]),
            payload.get("nextPageToken") or page.get("nextPageToken"),
        )
        issues.extend(batch)

        if page.get("isLast") is True:
            break

        total = page.get("total")
        max_results = page.get("maxResults", max_results) or max_results
        next_token = payload.get("nextPageToken") or page.get("nextPageToken")

        if total is not None and len(issues) >= total:
            break

        if not next_token:
            break

        next_page_token = next_token

    processed: List[Tuple[JiraIssue, List[JiraComment]]] = []
    remote_issue_keys: Set[str] = set()
    remote_comment_ids: Dict[str, Set[str]] = defaultdict(set)

    for issue in issues:
        if not isinstance(issue, Mapping):
            logger.warning(
                "Sync %s (job=%s): Skipping Jira issue with unexpected type %s: %s",
                sync.pk,
                sync.current_job_id,
                type(issue).__name__,
                _format_for_logging(issue),
            )
            continue

        issue_key = issue.get("key")
        fields = issue.get("fields")

        if not issue_key or not isinstance(fields, Mapping):
            logger.warning(
                "Sync %s (job=%s): Skipping Jira issue missing required data: %s",
                sync.pk,
                sync.current_job_id,
                _format_for_logging(issue),
            )
            continue

        remote_issue_keys.add(issue_key)

        summary = fields.get("summary", "")
        description = fields.get("description", "") or ""
        status_info = fields.get("status") or {}
        status_name = status_info.get("name", "") if isinstance(status_info, Mapping) else ""
        created_at = fields.get("created")
        updated_at = fields.get("updated")

        if not status_name:
            logger.warning(
                "Sync %s (job=%s): Jira issue %s missing status name; defaulting to empty string",
                sync.pk,
                sync.current_job_id,
                issue_key,
            )

        # Save or update the issue
        jira_issue, _ = JiraIssue.objects.update_or_create(
            sync=sync,
            issue_key=issue_key,
            defaults={
                "summary": summary,
                "description": description,
                "status": status_name,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        # Fetch and save comments
        comments = fetch_comments(base_url, issue_key, api_key, email, sync)
        synced_comments: List[JiraComment] = []
        for comment in comments:
            plain_text = extract_plain_text_from_adf(comment.get("body"))
            comment_remote_id = str(comment.get("id")) if comment.get("id") is not None else None
            author = comment["author"]["displayName"]
            created_at = comment["created"]
            content = plain_text if plain_text else "Unknown content"

            if comment_remote_id:
                comment_obj, _ = JiraComment.objects.update_or_create(
                    issue=jira_issue,
                    remote_id=comment_remote_id,
                    defaults={
                        "author": author,
                        "content": content,
                        "created_at": created_at,
                    },
                )
                remote_comment_ids[issue_key].add(f"remote:{comment_remote_id}")
            else:
                comment_obj, _ = JiraComment.objects.update_or_create(
                    issue=jira_issue,
                    author=author,
                    created_at=created_at,
                    content=content,
                    defaults={
                        "remote_id": comment_remote_id,
                    },
                )
                remote_comment_ids[issue_key].add(f"local:{comment_obj.pk}")
            synced_comments.append(comment_obj)

        processed.append((jira_issue, synced_comments))

    if processed:
        from django.utils import timezone

        sync.last_sync_time = timezone.now()
        sync.save(update_fields=["last_sync_time"])

    logger.info(
        "Fetched %s Jira issues for sync %s (job=%s)",
        len(processed),
        sync.pk,
        sync.current_job_id,
    )

    return processed, remote_issue_keys, remote_comment_ids

def ingest_jira_issue(company, chatbot, issue: JiraIssue, comments: Iterable[JiraComment] | None = None):
    """
    Ingest a Jira issue and its comments as documents.
    """
    issue_id = issue.issue_key
    content = f"Issue: {issue.summary}\n\nDescription: {issue.description}"
    documents = []
    issue_documents = save_document(
        company=company,
        chatbot=chatbot,
        source="jira_issue",
        source_id=issue_id,
        content=content
    )
    documents.extend(issue_documents)

    if comments:
        for comment in comments:
            comment_id = f"{issue_id}_comment_{comment.id}"
            comment_content = f"Comment by {comment.author} on {comment.created_at}:\n{comment.content}"
            comment_documents = save_document(
                company=company,
                chatbot=chatbot,
                source="jira_comment",
                source_id=comment_id,
                content=comment_content
            )
            documents.extend(comment_documents)

    return documents


def cleanup_removed_jira_content(
    sync: JiraSync,
    remote_issue_keys: Set[str],
    remote_comment_tokens: Dict[str, Set[str]],
) -> Tuple[int, int]:
    deleted_issues = 0
    deleted_comments = 0

    existing_issues = JiraIssue.objects.filter(sync=sync)
    issues_to_remove = list(existing_issues.exclude(issue_key__in=remote_issue_keys))

    if issues_to_remove:
        issue_ids = [issue.pk for issue in issues_to_remove]
        issue_keys = [issue.issue_key for issue in issues_to_remove]

        for issue in issues_to_remove:
            comment_ids = list(issue.comments.values_list("id", flat=True))
            if comment_ids:
                comment_source_ids = [f"{issue.issue_key}_comment_{comment_id}" for comment_id in comment_ids]
                deleted_comments += len(comment_ids)
                _delete_documents_for_source_ids("jira_comment", comment_source_ids)

        _delete_documents_for_source_ids("jira_issue", issue_keys)
        deleted_issues = len(issue_ids)
        existing_issues.filter(pk__in=issue_ids).delete()

    remaining_issues = JiraIssue.objects.filter(sync=sync, issue_key__in=remote_issue_keys)

    for issue in remaining_issues:
        tokens_to_keep = remote_comment_tokens.get(issue.issue_key, set())
        comment_qs = issue.comments.all()

        if tokens_to_keep:
            remote_ids_to_keep = {token.split(":", 1)[1] for token in tokens_to_keep if token.startswith("remote:")}
            local_ids_to_keep = {
                int(token.split(":", 1)[1])
                for token in tokens_to_keep
                if token.startswith("local:") and token.split(":", 1)[1].isdigit()
            }

            if remote_ids_to_keep:
                comment_qs = comment_qs.exclude(remote_id__in=remote_ids_to_keep)
            if local_ids_to_keep:
                comment_qs = comment_qs.exclude(pk__in=local_ids_to_keep)

        comments_to_delete = list(comment_qs)

        if not comments_to_delete:
            continue

        for comment in comments_to_delete:
            base_id = f"{issue.issue_key}_comment_{comment.pk}"
            _delete_documents_for_source_ids("jira_comment", [base_id])
        deleted_comments += len(comments_to_delete)
        issue.comments.filter(pk__in=[comment.pk for comment in comments_to_delete]).delete()

    return deleted_issues, deleted_comments
