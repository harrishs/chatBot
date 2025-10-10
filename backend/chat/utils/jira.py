import logging
from typing import Iterable, List, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from chat.encryption import decrypt_api_key
from urllib.parse import urlparse
from chat.models import JiraIssue, JiraComment, JiraSync
from chat.utils.embeddings import save_document


logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = (5, 30)


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

def get_base_domain(board_url):
    parsed = urlparse(board_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def fetch_comments(base_url, issue_key, api_key, email):
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
        response = _SESSION.get(
            url,
            headers=headers,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("comments", []) or []
        if not batch:
            break

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

def fetch_jira_issues(sync: JiraSync) -> List[Tuple[JiraIssue, List[JiraComment]]]:
    api_key = decrypt_api_key(sync.credential._api_key)
    project_key = extract_project_key(sync.board_url)
    base_url = get_base_domain(sync.board_url)
    email = sync.credential.email

    issue_url = f"{base_url}/rest/api/3/search"
    auth = requests.auth.HTTPBasicAuth(email, api_key)
    headers = {
        "Accept": "application/json"
    }

    issues: List[dict] = []
    start_at = 0
    max_results = 50

    while True:
        params = {
            "jql": f"project={project_key}",
            "startAt": start_at,
            "maxResults": max_results,
        }
        response = _SESSION.get(
            issue_url,
            headers=headers,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("issues", []) or []
        if not batch:
            break

        issues.extend(batch)

        if payload.get("isLast") is True:
            break

        batch_size = len(batch)
        total = payload.get("total")
        max_results = payload.get("maxResults", max_results) or max_results
        start_at = payload.get("startAt", start_at) + batch_size

        if total is not None and len(issues) >= total:
            break

        if batch_size < max_results:
            break

    processed: List[Tuple[JiraIssue, List[JiraComment]]] = []

    for issue in issues:
        issue_key = issue["key"]
        fields = issue["fields"]

        # Save or update the issue
        jira_issue, _ = JiraIssue.objects.update_or_create(
            sync=sync,
            issue_key=issue_key,
            defaults={
                "summary": fields["summary"],
                "description": fields.get("description", ""),
                "status": fields["status"]["name"],
                "created_at": fields["created"],
                "updated_at": fields["updated"]
            }
        )

        # Fetch and save comments
        comments = fetch_comments(base_url, issue_key, api_key, email)
        synced_comments: List[JiraComment] = []
        for comment in comments:
            plain_text = extract_plain_text_from_adf(comment.get("body"))
            comment_obj, _ = JiraComment.objects.update_or_create(
                issue=jira_issue,
                content=plain_text if plain_text else "Unknown content",
                created_at=comment["created"],
                author=comment["author"]["displayName"]
            )
            synced_comments.append(comment_obj)

        processed.append((jira_issue, synced_comments))

    if processed:
        from django.utils import timezone

        sync.last_sync_time = timezone.now()
        sync.save(update_fields=["last_sync_time"])

    logger.info("Fetched %s Jira issues for sync %s", len(processed), sync.pk)

    return processed

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
