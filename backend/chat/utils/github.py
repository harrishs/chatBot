import base64
import logging
from typing import Iterable, List, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone
from urllib.parse import quote
from chat.encryption import decrypt_api_key
from chat.models import GitRepoSync, GitRepoFile

GITHUB_API = "https://api.github.com"

# Simple allow-list of textual file extensions for MVP (tweak as needed)
TEXT_EXTS = {'.md', '.mdx', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yml', '.yaml', '.toml', '.ini', '.css', '.scss', '.html', '.c', '.cc', '.cpp', '.h', '.go', '.rs'}

MAX_FILE_BYTES = 500_000  # ~500KB per file to avoid massive blobs in DB


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

def _is_text_path(path: str) -> bool:
    for ext in TEXT_EXTS:
        if path.lower().endswith(ext):
            return True
    return False

def _gh_headers(token: str):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def _list_tree(full_name: str, branch: str, token: str):
    # Get the SHA for the branch head
    ref_url = f"{GITHUB_API}/repos/{full_name}/git/refs/heads/{quote(branch)}"
    r = _SESSION.get(ref_url, headers=_gh_headers(token), timeout=_REQUEST_TIMEOUT)
    r.raise_for_status()
    commit_sha = r.json()['object']['sha']

    # Get full recursive tree
    tree_url = f"{GITHUB_API}/repos/{full_name}/git/trees/{commit_sha}?recursive=1"
    t = _SESSION.get(tree_url, headers=_gh_headers(token), timeout=_REQUEST_TIMEOUT)
    t.raise_for_status()
    return t.json().get('tree', [])

def _get_blob(full_name: str, sha: str, token: str) -> bytes:
    blob_url = f"{GITHUB_API}/repos/{full_name}/git/blobs/{sha}"
    b = _SESSION.get(blob_url, headers=_gh_headers(token), timeout=_REQUEST_TIMEOUT)
    b.raise_for_status()
    data = b.json()
    if data.get('encoding') == 'base64':
        raw = base64.b64decode(data['content'])
        return raw
    return b.content

def _get_last_commit_date(full_name: str, path: str, token: str) -> datetime:
    # fetch last commit touching this file (lightweight; can be rate-limited)
    commits_url = f"{GITHUB_API}/repos/{full_name}/commits?path={quote(path)}&per_page=1"
    c = _SESSION.get(commits_url, headers=_gh_headers(token), timeout=_REQUEST_TIMEOUT)
    if c.status_code == 200 and isinstance(c.json(), list) and c.json():
        iso = c.json()[0]['commit']['committer']['date']  # ISO string
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    # fallback to now
    return datetime.now(timezone.utc)

def run_github_sync(sync: GitRepoSync) -> Tuple[int, int]:
    """
    Pull textual files from a repo branch and store/update GitRepoFile rows.
    Returns count of files indexed.
    """
    # decrypt token
    token = decrypt_api_key(sync.credential._token)
    full_name = sync.repo_full_name
    branch = sync.branch

    tree = _list_tree(full_name, branch, token)
    processed_files: List[GitRepoFile] = []
    count = 0
    for node in tree:
        if node.get('type') != 'blob':
            continue
        path = node['path']
        sha = node['sha']

        if not _is_text_path(path):
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
        processed_files.append(obj)

    # bump last_sync_time
    from django.utils import timezone
    sync.last_sync_time = timezone.now()
    sync.save(update_fields=['last_sync_time'])

    documents_ingested = ingest_github_files(sync, files=processed_files)
    logger.info(
        "Synced %s GitHub files and ingested %s documents for sync %s",
        count,
        documents_ingested,
        sync.pk,
    )
    return count, documents_ingested

def ingest_github_files(sync: GitRepoSync, files: Iterable[GitRepoFile] | None = None) -> int:
    """
    Ingest files from a GitRepoSync into the document store with embeddings.
    Returns count of files ingested.
    """
    from chat.utils.embeddings import save_document

    files_to_ingest = list(files) if files is not None else list(GitRepoFile.objects.filter(sync=sync))
    count = 0
    for f in files_to_ingest:
        docs = save_document(
            company=sync.chatBot.company,
            chatbot=sync.chatBot,
            source="github",
            source_id=f.id,
            content=f.content
        )
        count += len(docs)
    return count
