import logging
from typing import Iterable, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse, urlencode
from chat.models import ConfluencePage, ConfluenceSync
from chat.encryption import decrypt_api_key
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

def get_confluence_base_url(space_url):
    """
    Extract base URL from Confluence space URL
    Example: https://yourcompany.atlassian.net/wiki/spaces/ABC/pages/1234
    => https://yourcompany.atlassian.net
    """
    parsed = urlparse(space_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def extract_space_key(space_url):
    """
    Extract space key from Confluence space URL
    Example: https://yourcompany.atlassian.net/wiki/spaces/ABC/pages/1234
    => ABC
    """
    try:
        parts = space_url.split("/spaces/")
        if len(parts) > 1:
            return parts[1].split("/")[0]
    except Exception:
        logger.exception("Error extracting Confluence space key from URL")
    return ""

def fetch_confluence_pages(sync: ConfluenceSync) -> List[ConfluencePage]:
    try:
        api_key = decrypt_api_key(sync.credential._api_key)
        email = sync.credential.email
    except AttributeError:
        logger.error("Confluence credential missing for sync %s", sync.pk)
        raise

    base_url = get_confluence_base_url(sync.space_url)
    space_key = extract_space_key(sync.space_url)
    cql_query = f'space="{space_key}"'
    query_params = {
        "cql": cql_query,
        "expand": "body.storage,version",
        "limit": 100,  # Adjust limit as needed
    }
    query_string = urlencode(query_params)
    url = f"{base_url}/wiki/rest/api/content/search"

    auth = (email, api_key)
    headers = {
        "Accept": "application/json"
    }

    pages: List[dict] = []
    next_url: str | None = None
    params = query_params.copy()

    while True:
        try:
            response = _SESSION.get(
                next_url or url,
                auth=auth,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
                params=None if next_url else params,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch Confluence pages for sync %s", sync.pk)
            raise

        payload = response.json()
        batch = payload.get("results", []) or []
        if not batch:
            break

        pages.extend(batch)

        next_link = payload.get("_links", {}).get("next")
        if next_link:
            if next_link.startswith("http"):
                next_url = next_link
            else:
                next_url = f"{base_url}/wiki{next_link}" if not next_link.startswith("/wiki") else f"{base_url}{next_link}"
            continue

        start = payload.get("start")
        limit = payload.get("limit")
        size = payload.get("size")

        if start is None or limit is None:
            break

        next_start = start + limit
        if size is not None and next_start >= size:
            break

        params = {
            "cql": cql_query,
            "expand": "body.storage,version",
            "limit": limit,
            "start": next_start,
        }
        next_url = None

    processed: List[ConfluencePage] = []
    for page in pages:
        title = page.get("title", "")
        content = page.get("body", {}).get("storage", {}).get("value", "")
        last_updated = page.get("version", {}).get("when", "")
        page_url = f"{base_url}/wiki{page.get('_links', {}).get('webui', '')}"

        page_obj, _ = ConfluencePage.objects.update_or_create(
            sync=sync,
            title=title,
            defaults={
                "content": content,
                "url": page_url,
                "last_updated": last_updated
            }
        )
        processed.append(page_obj)

    if processed:
        from django.utils import timezone

        sync.last_sync_time = timezone.now()
        sync.save(update_fields=["last_sync_time"])

    logger.info("Fetched %s Confluence pages for sync %s", len(processed), sync.pk)

    return processed


def ingest_confluence_pages(sync: ConfluenceSync, pages: Iterable[ConfluencePage] | None = None) -> int:
    pages_to_ingest = list(pages) if pages is not None else list(ConfluencePage.objects.filter(sync=sync))
    documents_created = 0
    for page in pages_to_ingest:
        docs = save_document(
            company=sync.chatBot.company,
            chatbot=sync.chatBot,
            source="confluence",
            source_id=page.id,
            content=page.content
        )
        documents_created += len(docs)

    return documents_created
