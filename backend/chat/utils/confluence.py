import json
import logging
from typing import Any, Callable, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse
from django.db.models import Q

from chat.models import ConfluencePage, ConfluenceSync, Document
from chat.encryption import decrypt_api_key
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
    context: Optional[Mapping[str, Any]] = None,
    response_max_length: int = 512,
):
    context_str = _format_context(context)
    logger.debug(
        "Confluence API %sRequest %s %s params=%s",
        context_str,
        method.upper(),
        url,
        _format_for_logging(params),
    )
    try:
        response = request_func()
    except Exception:
        logger.debug(
            "Confluence API %sRequest %s %s failed before receiving a response",
            context_str,
            method.upper(),
            url,
        )
        raise

    logger.debug(
        "Confluence API %sResponse %s %s status=%s body=%s",
        context_str,
        method.upper(),
        url,
        getattr(response, "status_code", "unknown"),
        _format_for_logging(getattr(response, "text", ""), max_length=response_max_length),
    )
    return response


def _parse_query_params(url: str) -> Mapping[str, Any]:
    if not url:
        return {}
    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query, keep_blank_values=True))


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

def _build_confluence_document_source_id(page: ConfluencePage) -> Optional[str]:
    """Return a stable, human-friendly identifier for a Confluence page."""
    return page.url or page.remote_id


def _delete_documents_for_source_ids(sync: ConfluenceSync, base_ids: Iterable[str]) -> int:
    deleted = 0
    for base_id in base_ids:
        if base_id is None:
            continue
        conditions = Q(source_id=str(base_id)) | Q(source_id__startswith=f"{base_id}_part_")
        deleted += (
            Document.objects.filter(
                source="confluence",
                company=sync.chatBot.company,
                chatbot=sync.chatBot,
            )
            .filter(conditions)
            .delete()[0]
        )
    return deleted


def fetch_confluence_pages(sync: ConfluenceSync) -> Tuple[List[ConfluencePage], Set[str]]:
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
        request_url = next_url or url
        request_params = None if next_url else params
        if request_params is None:
            logged_params = _parse_query_params(request_url)
        else:
            logged_params = request_params
        context = {
            "sync_id": sync.pk,
            "next_url": next_url,
        }
        if request_params:
            context.update({
                "start": request_params.get("start"),
                "limit": request_params.get("limit"),
            })
        else:
            next_query = _parse_query_params(request_url)
            if next_query.get("start") is not None:
                context["start"] = next_query.get("start")
            if next_query.get("limit") is not None:
                context["limit"] = next_query.get("limit")

        try:
            response = _log_request_response(
                "GET",
                request_url,
                request_func=lambda: _SESSION.get(
                    request_url,
                    auth=auth,
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                    params=request_params,
                ),
                params=logged_params,
                context={k: v for k, v in context.items() if v is not None},
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
            parsed_next = urlparse(next_url)
            next_query = dict(parse_qsl(parsed_next.query, keep_blank_values=True))
            if "expand" not in next_query and query_params.get("expand"):
                next_query["expand"] = query_params["expand"]
            if "cql" not in next_query and query_params.get("cql"):
                next_query["cql"] = query_params["cql"]
            if "limit" not in next_query and query_params.get("limit"):
                next_query["limit"] = query_params["limit"]
            next_url = urlunparse(parsed_next._replace(query=urlencode(next_query)))
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
    remote_ids: Set[str] = set()
    for page in pages:
        title = page.get("title", "")
        content = page.get("body", {}).get("storage", {}).get("value", "")
        last_updated = page.get("version", {}).get("when", "")
        page_url = f"{base_url}/wiki{page.get('_links', {}).get('webui', '')}"
        remote_id = str(page.get("id")) if page.get("id") is not None else None

        if remote_id:
            remote_ids.add(remote_id)

        lookup_kwargs = {"sync": sync}
        if remote_id:
            lookup_kwargs["remote_id"] = remote_id
        else:
            lookup_kwargs["title"] = title

        defaults = {
            "title": title,
            "content": content,
            "url": page_url,
            "last_updated": last_updated,
        }

        page_obj, _ = ConfluencePage.objects.update_or_create(
            defaults=defaults,
            **lookup_kwargs,
        )
        processed.append(page_obj)

    if processed:
        from django.utils import timezone

        sync.last_sync_time = timezone.now()
        sync.save(update_fields=["last_sync_time"])

    logger.info("Fetched %s Confluence pages for sync %s", len(processed), sync.pk)

    return processed, remote_ids


def ingest_confluence_pages(sync: ConfluenceSync, pages: Iterable[ConfluencePage] | None = None) -> int:
    pages_to_ingest = list(pages) if pages is not None else list(ConfluencePage.objects.filter(sync=sync))
    documents_created = 0
    for page in pages_to_ingest:
        stable_source_id = _build_confluence_document_source_id(page)
        legacy_ids: List[str] = []
        if page.pk is not None:
            legacy_ids.append(str(page.pk))

        if legacy_ids:
            _delete_documents_for_source_ids(sync, legacy_ids)

        docs = save_document(
            company=sync.chatBot.company,
            chatbot=sync.chatBot,
            source="confluence",
            source_id=stable_source_id or str(page.pk),
            content=page.content
        )
        documents_created += len(docs)

    return documents_created


def cleanup_removed_confluence_pages(
    sync: ConfluenceSync,
    processed_pages: Iterable[ConfluencePage],
    remote_ids: Set[str],
) -> int:
    keep_page_ids = {page.pk for page in processed_pages}
    remote_ids = {remote_id for remote_id in remote_ids if remote_id}

    queryset = ConfluencePage.objects.filter(sync=sync)

    if remote_ids:
        queryset = queryset.exclude(remote_id__in=remote_ids)

    if keep_page_ids:
        queryset = queryset.exclude(pk__in=keep_page_ids)

    pages_to_delete = list(queryset)
    if not pages_to_delete:
        return 0

    source_ids_to_delete: List[str] = []
    for page in pages_to_delete:
        stable_id = _build_confluence_document_source_id(page)
        if stable_id:
            source_ids_to_delete.append(stable_id)
        if page.pk is not None:
            pk_id = str(page.pk)
            if pk_id != stable_id:
                source_ids_to_delete.append(pk_id)

    _delete_documents_for_source_ids(sync, source_ids_to_delete)
    ConfluencePage.objects.filter(pk__in=[page.pk for page in pages_to_delete]).delete()

    return len(pages_to_delete)
