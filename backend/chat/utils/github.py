import base64
import fnmatch
import requests
from datetime import datetime, timezone
from urllib.parse import quote
from chat.encryption import decrypt_api_key
from chat.models import GitRepoSync, GitRepoFile

GITHUB_API = "https://api.github.com"

# Simple allow-list of textual file extensions for MVP (tweak as needed)
TEXT_EXTS = {'.md', '.mdx', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yml', '.yaml', '.toml', '.ini', '.css', '.scss', '.html', '.c', '.cc', '.cpp', '.h', '.go', '.rs'}

MAX_FILE_BYTES = 500_000  # ~500KB per file to avoid massive blobs in DB

def _is_text_path(path: str) -> bool:
    for ext in TEXT_EXTS:
        if path.lower().endswith(ext):
            return True
    return False

def _match_include(path: str, include_globs: str) -> bool:
    """
    include_globs: comma-separated list of glob patterns, e.g.:
      "*.md,docs/**/*.md,src/**/*.ts"
    if blank -> accept all
    """
    if not include_globs.strip():
        return True
    patterns = [g.strip() for g in include_globs.split(",") if g.strip()]
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)

def _gh_headers(token: str):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def _list_tree(full_name: str, branch: str, token: str):
    # Get the SHA for the branch head
    ref_url = f"{GITHUB_API}/repos/{full_name}/git/refs/heads/{quote(branch)}"
    r = requests.get(ref_url, headers=_gh_headers(token))
    r.raise_for_status()
    commit_sha = r.json()['object']['sha']

    # Get full recursive tree
    tree_url = f"{GITHUB_API}/repos/{full_name}/git/trees/{commit_sha}?recursive=1"
    t = requests.get(tree_url, headers=_gh_headers(token))
    t.raise_for_status()
    return t.json().get('tree', [])

def _get_blob(full_name: str, sha: str, token: str) -> bytes:
    blob_url = f"{GITHUB_API}/repos/{full_name}/git/blobs/{sha}"
    b = requests.get(blob_url, headers=_gh_headers(token))
    b.raise_for_status()
    data = b.json()
    if data.get('encoding') == 'base64':
        raw = base64.b64decode(data['content'])
        return raw
    return b.content

def _get_last_commit_date(full_name: str, path: str, token: str) -> datetime:
    # fetch last commit touching this file (lightweight; can be rate-limited)
    commits_url = f"{GITHUB_API}/repos/{full_name}/commits?path={quote(path)}&per_page=1"
    c = requests.get(commits_url, headers=_gh_headers(token))
    if c.status_code == 200 and isinstance(c.json(), list) and c.json():
        iso = c.json()[0]['commit']['committer']['date']  # ISO string
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    # fallback to now
    return datetime.now(timezone.utc)

def run_github_sync(sync: GitRepoSync) -> int:
    """
    Pull textual files from a repo branch and store/update GitRepoFile rows.
    Returns count of files indexed.
    """
    # decrypt token
    token = decrypt_api_key(sync.credential._token)
    full_name = sync.repo_full_name
    branch = sync.branch

    tree = _list_tree(full_name, branch, token)
    count = 0
    for node in tree:
        if node.get('type') != 'blob':
            continue
        path = node['path']
        sha = node['sha']

        if not _is_text_path(path):
            continue
        if not _match_include(path, sync.include_globs or ""):
            continue

        blob = _get_blob(full_name, sha, token)
        if not blob or len(blob) > MAX_FILE_BYTES:
            continue

        try:
            text = blob.decode('utf-8', errors='replace')
        except Exception:
            continue

        last_update = _get_last_commit_date(full_name, path, token)
        html_url = f"https://github.com/{full_name}/blob/{quote(branch)}/{path}"

        obj, _created = GitRepoFile.objects.update_or_create(
            sync=sync, path=path,
            defaults={
                'sha': sha,
                'size': len(blob),
                'url': html_url,
                'content': text,
                'last_updated': last_update,
            }
        )
        count += 1

    # bump last_sync_time
    from django.utils import timezone
    sync.last_sync_time = timezone.now()
    sync.save(update_fields=['last_sync_time'])
    return count
