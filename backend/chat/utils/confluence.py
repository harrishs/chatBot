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
    url = f"{base_url}/wiki/rest/api/content/search?{query_string}"

    auth = (email, api_key)
    headers = {
        "Accept": "application/json"
    }

    try:
        response = _SESSION.get(url, auth=auth, headers=headers, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to fetch Confluence pages for sync %s", sync.pk)
        raise

    pages = response.json().get("results", [])

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
