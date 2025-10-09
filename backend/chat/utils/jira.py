import logging
from typing import Iterable, List, Tuple

import requests
from chat.encryption import decrypt_api_key
from urllib.parse import urlparse
from chat.models import JiraIssue, JiraComment, JiraSync
from chat.utils.embeddings import save_document


logger = logging.getLogger(__name__)

def extract_project_key(board_url):
    # Example: https://yourdomain.atlassian.net/jira/software/c/projects/CPG/boards/1
    # Extract 'CPG' between /projects/ and /boards/
    try:
        parts = board_url.split("/projects/")
        if len(parts) > 1:
            project_part = parts[1].split("/")[0]
            return project_part
    except Exception as e:
        print(f"Error extracting project key: {e}")
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

    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()

    return response.json().get("comments", [])

def fetch_jira_issues(sync: JiraSync) -> List[Tuple[JiraIssue, List[JiraComment]]]:
    api_key = decrypt_api_key(sync.credential._api_key)
    project_key = extract_project_key(sync.board_url)
    base_url = get_base_domain(sync.board_url)
    email = sync.credential.email

    issue_url = f"{base_url}/rest/api/3/search?jql=project={project_key}"
    auth = requests.auth.HTTPBasicAuth(email, api_key)
    headers = {
        "Accept": "application/json"
    }

    response = requests.get(issue_url, headers=headers, auth=auth)
    response.raise_for_status()
    issues = response.json().get("issues", [])

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
            comment_obj, _ = JiraComment.objects.update_or_create(
                issue=jira_issue,
                content=comment["body"]["content"][0]["content"][0]["text"]
                    if "content" in comment["body"] and comment["body"]["content"]
                    else "Unknown content",
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
