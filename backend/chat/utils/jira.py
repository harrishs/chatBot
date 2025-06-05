import requests
from chat.encryption import decrypt_api_key
from urllib.parse import urlparse
from chat.models import JiraIssue, JiraComment

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

def fetch_jira_issues(sync):
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
        for comment in comments:
            JiraComment.objects.update_or_create(
                issue=jira_issue,
                content=comment["body"]["content"][0]["content"][0]["text"]
                    if "content" in comment["body"] and comment["body"]["content"]
                    else "Unknown content",
                created_at=comment["created"],
                author=comment["author"]["displayName"]
            )

