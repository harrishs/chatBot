import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from math import sqrt
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from django.conf import settings
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramSimilarity,
)
from django.db import connection
from django.db.models import Case, ExpressionWrapper, F, FloatField, Q, Value, When
from django.db.models import Max
from django.db.models import Window
from django.db.models.functions import Coalesce
from django.db.models.functions import NullIf
from django.utils import timezone
from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from pgvector.django import CosineDistance

from chat.models import ChatFeedback, Document

try:  # pragma: no cover - optional dependency
    import tiktoken
except Exception:  # pragma: no cover - guard against unexpected import issues
    tiktoken = None


logger = logging.getLogger(__name__)

_shared_openai_client = None

_MAX_CHUNK_TEXT_CHARACTERS = 1800

_RETRIEVAL_FALLBACK_CACHE: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
_MAX_FALLBACK_CACHE_SIZE = 200

_EMBEDDING_MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "text-embedding-3-small": 8192,
    "text-embedding-3-large": 8192,
    "text-embedding-ada-002": 8192,
}


def _embedding_model_context_limit(model_name: str) -> int:
    configured_limit = getattr(settings, "OPENAI_EMBEDDING_CONTEXT_LIMIT", None)
    if configured_limit:
        try:
            return max(1, int(configured_limit))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid OPENAI_EMBEDDING_CONTEXT_LIMIT value %r; falling back to defaults.",
                configured_limit,
            )

    normalized = (model_name or "").strip().lower()
    if normalized in _EMBEDDING_MODEL_CONTEXT_LIMITS:
        return _EMBEDDING_MODEL_CONTEXT_LIMITS[normalized]

    return 8192


def _segment_character_limit(max_tokens: int, *, model_name: str) -> Optional[int]:
    configured_limit = getattr(settings, "OPENAI_EMBEDDING_SEGMENT_CHAR_LIMIT", None)
    if configured_limit is not None:
        try:
            limit_value = int(configured_limit)
            return max(1, limit_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid OPENAI_EMBEDDING_SEGMENT_CHAR_LIMIT value %r; ignoring override.",
                configured_limit,
            )

    approx_chars_per_token = getattr(settings, "OPENAI_EMBEDDING_APPROX_CHARS_PER_TOKEN", 4)
    try:
        approx_chars_per_token = max(1, int(approx_chars_per_token))
    except (TypeError, ValueError):
        approx_chars_per_token = 4

    context_limit = _embedding_model_context_limit(model_name)
    # Heuristically bound character count based on desired max token size for each chunk.
    per_chunk_limit = max_tokens * approx_chars_per_token
    model_limit = context_limit * approx_chars_per_token
    return max(1, min(per_chunk_limit, model_limit))


def _split_text_to_max_characters(text: str, limit: Optional[int]) -> List[str]:
    if not text:
        return []
    if not limit or limit <= 0 or len(text) <= limit:
        return [text.strip()]

    parts: List[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(text_length, start + limit)
        if end < text_length:
            newline_break = text.rfind("\n", start, end)
            space_break = text.rfind(" ", start, end)
            break_point = max(newline_break, space_break)
            if break_point <= start:
                break_point = end
            end = break_point

        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
        start = max(end, start + 1)

    return parts or [text[:limit].strip()]


def _estimate_token_count(text: str, *, model_name: str) -> int:
    if not text:
        return 0

    if tiktoken is not None:
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        try:
            return len(encoding.encode(text, disallowed_special=()))
        except Exception:  # pragma: no cover - guard against unexpected encoding issues
            pass

    # Fallback approximation assuming ~4 characters per token.
    return max(1, (len(text) + 3) // 4)


def _trim_text_to_token_limit(
    text: str,
    *,
    max_tokens: int,
    model_name: str,
    fallback_char_limit: Optional[int] = None,
) -> str:
    trimmed = (text or "").strip()
    if not trimmed or max_tokens <= 0:
        return ""

    if _estimate_token_count(trimmed, model_name=model_name) <= max_tokens:
        return trimmed

    low = 0
    high = len(trimmed)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = trimmed[:mid].rstrip()
        if not candidate:
            high = mid - 1
            continue

        token_count = _estimate_token_count(candidate, model_name=model_name)
        if token_count <= max_tokens:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1

    if best:
        return best

    if fallback_char_limit and fallback_char_limit > 0:
        return trimmed[:fallback_char_limit].rstrip()

    return ""


def record_retrieval_fallback_event(
    *,
    event_type: str,
    company_id: int,
    chatbot_id: int,
    query: str,
    improved: bool,
    details: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Cache and log fallback attempts for later inspection."""

    fingerprint_source = f"{event_type}:{company_id}:{chatbot_id}:{query}".encode("utf-8")
    fingerprint = hashlib.sha256(fingerprint_source).hexdigest()

    entry: Dict[str, object] = {
        "timestamp": timezone.now(),
        "event_type": event_type,
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "query": query,
        "improved": bool(improved),
        "details": details or {},
    }

    _RETRIEVAL_FALLBACK_CACHE[fingerprint] = entry
    while len(_RETRIEVAL_FALLBACK_CACHE) > _MAX_FALLBACK_CACHE_SIZE:
        _RETRIEVAL_FALLBACK_CACHE.popitem(last=False)

    logger.info(
        "RAG retrieval fallback triggered: type=%s improved=%s details=%s",
        event_type,
        improved,
        details or {},
    )

    return entry


def get_openai_client() -> OpenAI:
    """Return a shared OpenAI client instance configured from settings."""
    global _shared_openai_client

    if _shared_openai_client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in environment or settings.py")

        _shared_openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

    return _shared_openai_client

def embed_text(text: str, *, model: Optional[str] = None) -> List[float]:
    """Generate a vector embedding for a given text using OpenAI."""

    client = get_openai_client()

    model_name = (model or getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")).strip()
    if not model_name:
        raise ValueError("An embedding model must be specified for embed_text")

    max_attempts = 6
    base_backoff_seconds = 1
    max_backoff_seconds = 10

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.embeddings.create(
                model=model_name,
                input=text,
            )
            return list(response.data[0].embedding)
        except RateLimitError as exc:
            if attempt < max_attempts:
                sleep_seconds = min(
                    base_backoff_seconds * (2 ** (attempt - 1)),
                    max_backoff_seconds,
                )
                logger.warning(
                    "OpenAI rate limit encountered for model '%s' (attempt %d/%d). Retrying after %d seconds.",
                    model_name,
                    attempt,
                    max_attempts,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue

            final_message = getattr(exc, "message", str(exc))
            logger.error(
                "OpenAI rate limit persisted after %d attempts while generating embeddings with model '%s': %s",
                max_attempts,
                model_name,
                final_message,
            )
            raise RuntimeError(
                "OpenAI embeddings sync failed after repeated rate limit errors; aborting job."
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise RuntimeError("Failed to reach OpenAI while generating embeddings") from exc


def _cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors."""

    if vec1 is None or vec2 is None:
        return 0.0

    try:
        length1 = len(vec1)
        length2 = len(vec2)
    except TypeError:
        vec1 = list(vec1)
        vec2 = list(vec2)
        length1 = len(vec1)
        length2 = len(vec2)

    if length1 == 0 or length2 == 0:
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return dot / (sqrt(norm1) * sqrt(norm2))


def _tokenize_query(text: str) -> List[str]:
    """Tokenize the query for simple lexical scoring."""

    return [token for token in (text or "").lower().split() if token]


def _trigram_similarity(query: str, text: str) -> float:
    """Approximate trigram similarity for SQLite fallbacks."""

    if not query or not text:
        return 0.0

    def _trigrams(value: str) -> List[str]:
        normalized = f"  {value.lower()} "
        return [normalized[i : i + 3] for i in range(len(normalized) - 2)]

    query_trigrams = _trigrams(query)
    text_trigrams = _trigrams(text)

    if not query_trigrams or not text_trigrams:
        return 0.0

    query_set = set(query_trigrams)
    text_set = set(text_trigrams)
    intersection = query_set.intersection(text_set)
    if not intersection:
        return 0.0

    return (2.0 * len(intersection)) / (len(query_set) + len(text_set))

def _normalize_metadata(metadata: Optional[Mapping[str, object]]) -> Dict[str, object]:
    if not metadata:
        return {}

    if not isinstance(metadata, Mapping):  # pragma: no cover - defensive
        raise TypeError("metadata must be a mapping if provided")

    normalized: Dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            normalized[str(key)] = value
        elif isinstance(value, Mapping):
            normalized[str(key)] = _normalize_metadata(value)
        elif isinstance(value, (list, tuple, set)):
            normalized[str(key)] = [
                item
                if isinstance(item, (str, int, float, bool)) or item is None
                else str(item)
                for item in value
            ]
        else:
            normalized[str(key)] = str(value)

    return normalized


def _bounded_chunk_text(value: str, max_characters: int = _MAX_CHUNK_TEXT_CHARACTERS) -> str:
    """Return ``value`` trimmed to ``max_characters`` while preserving newlines."""

    if not value:
        return ""

    normalized = value.strip("\n")
    if len(normalized) <= max_characters:
        return normalized

    truncated = normalized[:max_characters].rstrip()
    return f"{truncated}…"


def _split_paragraphs_with_headings(text: str) -> List[Tuple[str, Optional[str]]]:
    paragraphs: List[Tuple[str, Optional[str]]] = []
    active_heading: Optional[str] = None
    buffer: List[str] = []

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^(#+)\s*(.+)?$", stripped)
        if heading_match:
            if buffer:
                paragraph_text = "\n".join(buffer).strip()
                if paragraph_text:
                    paragraphs.append((paragraph_text, active_heading))
                buffer = []

            heading_value = (heading_match.group(2) or "").strip() or None
            active_heading = heading_value or active_heading
            paragraphs.append((stripped, heading_value))
            continue

        if not stripped:
            if buffer:
                paragraph_text = "\n".join(buffer).strip()
                if paragraph_text:
                    paragraphs.append((paragraph_text, active_heading))
                buffer = []
            continue

        buffer.append(line)

    if buffer:
        paragraph_text = "\n".join(buffer).strip()
        if paragraph_text:
            paragraphs.append((paragraph_text, active_heading))

    if not paragraphs and text.strip():
        paragraphs.append((text.strip(), active_heading))

    return paragraphs


def _segments_with_overlap(
    text: str,
    *,
    max_tokens: int = 1000,
    overlap_tokens: int = 100,
    max_characters: Optional[int] = None,
) -> List[Tuple[str, Optional[str], bool]]:
    normalized_max_tokens = max(1, int(max_tokens or 1))
    normalized_overlap = max(0, min(int(overlap_tokens or 0), normalized_max_tokens - 1))

    paragraphs = _split_paragraphs_with_headings(text)
    if not paragraphs:
        return []

    segments: List[Tuple[str, Optional[str], bool]] = []
    current_parts: List[str] = []
    current_tokens = 0
    current_heading: Optional[str] = None
    chunk_has_new_content = False

    def finalize_chunk() -> None:
        nonlocal current_parts, current_tokens, current_heading, chunk_has_new_content

        if not current_parts or not chunk_has_new_content:
            current_parts = []
            current_tokens = 0
            chunk_has_new_content = False
            return

        chunk_text = "\n\n".join(part.strip() for part in current_parts if part.strip()).strip()
        if not chunk_text:
            current_parts = []
            current_tokens = 0
            chunk_has_new_content = False
            return

        chunk_parts = _split_text_to_max_characters(chunk_text, max_characters)
        chunk_was_truncated = len(chunk_parts) > 1 or (
            max_characters is not None and len(chunk_text) > max_characters
        )

        for part_text in chunk_parts:
            if part_text:
                segments.append((part_text, current_heading, chunk_was_truncated))

        if normalized_overlap and chunk_parts:
            tokens = chunk_parts[-1].split()
            overlap_count = min(len(tokens), normalized_overlap)
            overlap_text = " ".join(tokens[-overlap_count:]) if overlap_count else ""
            current_parts = [overlap_text] if overlap_text else []
            current_tokens = overlap_count
            chunk_has_new_content = False
        else:
            current_parts = []
            current_tokens = 0
            chunk_has_new_content = False

    for paragraph_text, paragraph_heading in paragraphs:
        paragraph_text = paragraph_text.strip()
        if not paragraph_text:
            continue

        paragraph_tokens = paragraph_text.split()
        paragraph_token_count = len(paragraph_tokens)
        if not paragraph_token_count:
            continue

        available_tokens = normalized_max_tokens - current_tokens
        if current_parts and available_tokens < paragraph_token_count:
            finalize_chunk()

        token_index = 0
        while token_index < paragraph_token_count:
            available_tokens = normalized_max_tokens - current_tokens
            if available_tokens <= 0:
                finalize_chunk()
                continue

            take = min(paragraph_token_count - token_index, available_tokens)
            if take <= 0:
                break

            slice_tokens = paragraph_tokens[token_index : token_index + take]
            slice_text = " ".join(slice_tokens).strip()
            token_index += take

            if not slice_text:
                continue

            if not current_parts or not chunk_has_new_content:
                current_heading = paragraph_heading or current_heading

            current_parts.append(slice_text)
            current_tokens += len(slice_tokens)
            current_heading = paragraph_heading or current_heading
            chunk_has_new_content = True

    finalize_chunk()

    return segments


def _format_metadata_for_embedding(metadata: Mapping[str, object]) -> str:
    if not metadata:
        return ""

    lines: List[str] = []
    for key, value in metadata.items():
        if value in (None, ""):
            continue
        label = str(key).replace("_", " ").strip().title()
        if isinstance(value, list):
            filtered = [str(item) for item in value if item not in (None, "")]
            if not filtered:
                continue
            joined = ", ".join(filtered)
            lines.append(f"{label}: {joined}")
        elif isinstance(value, Mapping):
            nested = _format_metadata_for_embedding(value)
            if nested:
                lines.append(f"{label}: {nested}")
        else:
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def _normalize_source_id(source_id: str) -> str:
    if not source_id:
        return source_id
    return source_id.split("_part_", 1)[0]


def _document_metadata_for_search(doc: Document) -> Tuple[str, Optional[str], Dict[str, object]]:
    raw_metadata = doc.metadata if isinstance(doc.metadata, Mapping) else {}
    metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}

    normalized_source_id = _normalize_source_id(doc.source_id)
    source_display = metadata.get("source_display") or normalized_source_id
    source_url = metadata.get("source_url")
    if not source_url and normalized_source_id and normalized_source_id.startswith("http"):
        source_url = normalized_source_id

    return source_display, source_url, metadata


def save_document(
    *,
    company,
    chatbot,
    source,
    source_id,
    content,
    metadata: Optional[Mapping[str, object]] = None,
    max_tokens: int = 1000,
    overlap_tokens: int = 100,
):
    """Persist a document broken into overlapping segments with metadata-aware embeddings."""

    normalized_metadata = _normalize_metadata(metadata)
    model_name = (
        getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        or "text-embedding-3-small"
    ).strip()
    if not model_name:
        model_name = "text-embedding-3-small"

    context_limit_tokens = _embedding_model_context_limit(model_name)
    segment_char_limit = _segment_character_limit(max_tokens, model_name=model_name)

    raw_segments = _segments_with_overlap(
        content,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        max_characters=segment_char_limit,
    )

    prepared_segments: List[Dict[str, object]] = []
    for segment_text, section_heading, was_char_truncated in raw_segments:
        normalized_text = (segment_text or "").strip()
        if not normalized_text:
            continue
        prepared_segments.append(
            {
                "text": normalized_text,
                "heading": section_heading,
                "char_truncated": bool(was_char_truncated),
                "truncation_reasons": ["char_limit"] if was_char_truncated else [],
                "omit_chunk_text_in_metadata": False,
                "suppress_all_metadata": False,
            }
        )

    if not prepared_segments:
        return []

    changed = True
    while changed and prepared_segments:
        changed = False
        idx = 0
        while idx < len(prepared_segments):
            segment = prepared_segments[idx]
            segment_text = str(segment.get("text", ""))
            if not segment_text:
                prepared_segments.pop(idx)
                changed = True
                continue

            chunk_metadata = dict(normalized_metadata)
            heading_value = segment.get("heading")
            if not heading_value:
                heading_match = re.search(r"^#+\s*(.+)$", segment_text, re.MULTILINE)
                if heading_match:
                    heading_value = (heading_match.group(1) or "").strip() or None
                    segment["heading"] = heading_value
            if heading_value:
                chunk_metadata["section_heading"] = heading_value

            chunk_metadata["chunk_index"] = idx
            chunk_metadata["chunk_count"] = len(prepared_segments)
            chunk_metadata["chunk_char_count"] = len(segment_text)
            chunk_metadata["chunk_tokens"] = len(re.findall(r"\S+", segment_text))
            chunk_metadata["chunk_text"] = _bounded_chunk_text(segment_text)

            metadata_full = _format_metadata_for_embedding(chunk_metadata)
            embedding_full = segment_text
            if metadata_full:
                embedding_full = (
                    f"{metadata_full}\n\n{embedding_full}"
                    if embedding_full
                    else metadata_full
                )
            tokens_full = _estimate_token_count(embedding_full, model_name=model_name)
            if tokens_full <= context_limit_tokens:
                idx += 1
                continue

            reduced_metadata = {
                key: value
                for key, value in chunk_metadata.items()
                if key not in {"chunk_text", "chunk_char_count", "chunk_tokens"}
            }
            metadata_without_chunk = _format_metadata_for_embedding(reduced_metadata)
            embedding_without_chunk = segment_text
            if metadata_without_chunk:
                embedding_without_chunk = (
                    f"{metadata_without_chunk}\n\n{embedding_without_chunk}"
                    if embedding_without_chunk
                    else metadata_without_chunk
                )
            tokens_without_chunk = _estimate_token_count(
                embedding_without_chunk,
                model_name=model_name,
            )
            if tokens_without_chunk <= context_limit_tokens:
                if not segment.get("omit_chunk_text_in_metadata"):
                    segment["omit_chunk_text_in_metadata"] = True
                    changed = True
                idx += 1
                continue

            available_tokens = max(
                context_limit_tokens
                - _estimate_token_count(metadata_without_chunk, model_name=model_name),
                0,
            )
            trimmed_text = _trim_text_to_token_limit(
                segment_text,
                max_tokens=available_tokens,
                model_name=model_name,
                fallback_char_limit=segment_char_limit,
            )
            if trimmed_text and trimmed_text != segment_text:
                segment["text"] = trimmed_text
                segment["omit_chunk_text_in_metadata"] = True
                segment["char_truncated"] = True
                segment.setdefault("truncation_reasons", []).append("token_limit")
                changed = True
                continue

            trimmed_text = _trim_text_to_token_limit(
                segment_text,
                max_tokens=context_limit_tokens,
                model_name=model_name,
                fallback_char_limit=segment_char_limit,
            )
            if trimmed_text and trimmed_text != segment_text:
                segment["text"] = trimmed_text
                segment["omit_chunk_text_in_metadata"] = True
                segment["suppress_all_metadata"] = True
                segment["char_truncated"] = True
                segment.setdefault("truncation_reasons", []).append("token_limit")
                changed = True
                continue

            logger.warning(
                "Dropping embedding chunk for source %s at temporary index %d due to size overflow.",
                source_id,
                idx,
            )
            prepared_segments.pop(idx)
            changed = True
            break

        if idx >= len(prepared_segments):
            continue

    if not prepared_segments:
        return []

    docs = []
    truncated_chunks: List[str] = []
    total_segments = len(prepared_segments)

    for idx, segment in enumerate(prepared_segments):
        segment_text = str(segment.get("text", "")).strip()
        if not segment_text:
            logger.warning(
                "Skipping embedding chunk for source %s index %d due to empty content after truncation.",
                source_id,
                idx,
            )
            continue

        chunk_metadata = dict(normalized_metadata)
        heading_value = segment.get("heading")
        if not heading_value:
            heading_match = re.search(r"^#+\s*(.+)$", segment_text, re.MULTILINE)
            if heading_match:
                heading_value = (heading_match.group(1) or "").strip() or None
        if heading_value:
            chunk_metadata["section_heading"] = heading_value
        chunk_metadata["chunk_index"] = idx
        chunk_metadata["chunk_count"] = total_segments
        chunk_metadata["chunk_char_count"] = len(segment_text)
        chunk_metadata["chunk_tokens"] = len(re.findall(r"\S+", segment_text))
        chunk_metadata["chunk_text"] = _bounded_chunk_text(segment_text)

        if segment.get("char_truncated"):
            chunk_metadata["chunk_truncated"] = True
            reasons = sorted(set(segment.get("truncation_reasons") or []))
            if reasons:
                chunk_metadata["chunk_truncated_reason"] = ",".join(reasons)
            truncated_chunks.append(
                f"{source_id}[{idx}] ({chunk_metadata.get('chunk_truncated_reason', 'truncated')})"
            )
        else:
            chunk_metadata["chunk_truncated"] = False

        metadata_mode = "full"
        if segment.get("suppress_all_metadata"):
            metadata_mode = "content_only"
            metadata_for_embedding: Mapping[str, object] = {}
        elif segment.get("omit_chunk_text_in_metadata"):
            metadata_mode = "no_chunk_text"
            metadata_for_embedding = {
                key: value
                for key, value in chunk_metadata.items()
                if key not in {"chunk_text", "chunk_char_count", "chunk_tokens"}
            }
        else:
            metadata_for_embedding = chunk_metadata
        chunk_metadata["chunk_metadata_mode"] = metadata_mode

        metadata_text = _format_metadata_for_embedding(metadata_for_embedding)
        embedding_input = segment_text
        if metadata_text:
            embedding_input = f"{metadata_text}\n\n{embedding_input}" if embedding_input else metadata_text

        total_tokens = _estimate_token_count(embedding_input, model_name=model_name)
        if total_tokens > context_limit_tokens:
            available_tokens = max(
                context_limit_tokens
                - _estimate_token_count(metadata_text, model_name=model_name),
                0,
            )
            trimmed_text = _trim_text_to_token_limit(
                segment_text,
                max_tokens=available_tokens or context_limit_tokens,
                model_name=model_name,
                fallback_char_limit=segment_char_limit,
            )
            if trimmed_text and trimmed_text != segment_text:
                segment_text = trimmed_text
                chunk_metadata["chunk_char_count"] = len(segment_text)
                chunk_metadata["chunk_tokens"] = len(re.findall(r"\S+", segment_text))
                chunk_metadata["chunk_text"] = _bounded_chunk_text(segment_text)
                chunk_metadata["chunk_truncated"] = True
                reasons = set(segment.get("truncation_reasons") or [])
                reasons.add("token_limit")
                chunk_metadata["chunk_truncated_reason"] = ",".join(sorted(reasons))
                truncated_chunks.append(
                    f"{source_id}[{idx}] ({chunk_metadata.get('chunk_truncated_reason', 'truncated')})"
                )
                embedding_input = segment_text
                if metadata_text and metadata_mode != "content_only":
                    embedding_input = (
                        f"{metadata_text}\n\n{embedding_input}"
                        if embedding_input
                        else metadata_text
                    )
                total_tokens = _estimate_token_count(
                    embedding_input,
                    model_name=model_name,
                )

        if total_tokens > context_limit_tokens:
            metadata_text = ""
            embedding_input = segment_text
            total_tokens = _estimate_token_count(embedding_input, model_name=model_name)
            if total_tokens > context_limit_tokens:
                trimmed_text = _trim_text_to_token_limit(
                    segment_text,
                    max_tokens=context_limit_tokens,
                    model_name=model_name,
                    fallback_char_limit=segment_char_limit,
                )
                if not trimmed_text:
                    logger.warning(
                        "Skipping embedding chunk for source %s index %d because it exceeds context limits even after trimming.",
                        source_id,
                        idx,
                    )
                    continue
                segment_text = trimmed_text
                chunk_metadata["chunk_char_count"] = len(segment_text)
                chunk_metadata["chunk_tokens"] = len(re.findall(r"\S+", segment_text))
                chunk_metadata["chunk_text"] = _bounded_chunk_text(segment_text)
                chunk_metadata["chunk_truncated"] = True
                reasons = set(segment.get("truncation_reasons") or [])
                reasons.add("token_limit")
                chunk_metadata["chunk_truncated_reason"] = ",".join(sorted(reasons))
                truncated_chunks.append(
                    f"{source_id}[{idx}] ({chunk_metadata.get('chunk_truncated_reason', 'truncated')})"
                )
                embedding_input = segment_text

        if not embedding_input:
            logger.warning(
                "Skipping embedding chunk for source %s index %d due to empty embedding input.",
                source_id,
                idx,
            )
            continue

        embedding = embed_text(embedding_input)
        chunk_id = f"{source_id}_part_{idx}" if total_segments > 1 else source_id

        doc, _ = Document.objects.update_or_create(
            company=company,
            chatbot=chatbot,
            source=source,
            source_id=chunk_id,
            defaults={
                "content": embedding_input,
                "embedding": embedding,
                "metadata": chunk_metadata,
                "rerank_cache": {},
            },
        )
        docs.append(doc)

    if truncated_chunks:
        logger.info(
            "Embedding chunks truncated for source %s: %s",
            source_id,
            "; ".join(truncated_chunks),
        )

    return docs


def _feedback_source_id(feedback: ChatFeedback) -> str:
    return f"feedback-{feedback.id}"


def delete_feedback_document(feedback: ChatFeedback) -> int:
    """Remove any embedded documents associated with ``feedback``."""

    if not feedback or not feedback.id:
        return 0

    base_id = _feedback_source_id(feedback)
    conditions = Q(source_id=base_id) | Q(source_id__startswith=f"{base_id}_part_")

    deleted, _ = (
        Document.objects.filter(
            company=feedback.chatBot.company,
            chatbot=feedback.chatBot,
            source="feedback",
        )
        .filter(conditions)
        .delete()
    )
    return int(deleted)


def upsert_feedback_document(feedback: ChatFeedback) -> List[Document]:
    """Create or update embedded documents for ``feedback`` records."""

    if not feedback or not feedback.id:
        return []

    comment = (feedback.comment or "").strip()
    question = (feedback.question or "").strip()
    answer = (feedback.answer or "").strip()
    helpful = feedback.is_helpful

    if not any([comment, question, answer]):
        delete_feedback_document(feedback)
        return []

    summary_pieces: List[str] = []
    if question:
        summary_pieces.append(f"Question: {question}")
    if answer:
        summary_pieces.append(f"Assistant answer: {answer}")
    if helpful is not None:
        helpful_label = "helpful" if helpful else "not helpful"
        summary_pieces.append(f"Marked as {helpful_label} by the user")
    if comment:
        summary_pieces.append(f"Comment: {comment}")

    content = "\n\n".join(summary_pieces).strip()
    if not content:
        delete_feedback_document(feedback)
        return []

    base_id = _feedback_source_id(feedback)
    created_at = feedback.created_at.isoformat() if feedback.created_at else None

    def _shorten(value: str, limit: int = 80) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 1].rstrip() + "…"

    title = question or (comment and _shorten(comment)) or "User feedback"
    summary = comment or answer or question or "User feedback entry"
    feedback_kind = "structured" if question and answer else "comment"

    metadata: Dict[str, object] = {
        "feedback_id": feedback.id,
        "source_display": base_id,
        "title": title,
        "summary": _shorten(summary, 200),
        "submitted_at": created_at,
        "feedback_type": feedback_kind,
    }

    if question:
        metadata["question"] = question
    if answer:
        metadata["answer"] = answer
    if comment:
        metadata["comment"] = comment
    if helpful is not None:
        metadata["is_helpful"] = bool(helpful)

    documents = save_document(
        company=feedback.chatBot.company,
        chatbot=feedback.chatBot,
        source="feedback",
        source_id=base_id,
        content=content,
        metadata=metadata,
        max_tokens=600,
        overlap_tokens=60,
    )

    expected_ids = {doc.source_id for doc in documents}
    base_conditions = Q(source_id=base_id) | Q(source_id__startswith=f"{base_id}_part_")
    Document.objects.filter(
        company=feedback.chatBot.company,
        chatbot=feedback.chatBot,
        source="feedback",
    ).filter(base_conditions).exclude(source_id__in=expected_ids).delete()

    return documents


def _search_documents_single(
    *,
    company_id: int,
    chatbot_id: int,
    query: str,
    top_k: int,
    sources: Optional[Iterable[str]],
    query_embedding: Sequence[float],
    query_tokens: Sequence[str],
    lexical_only: bool,
) -> List[Dict[str, object]]:
    """Execute a single retrieval pass with the configured scoring strategy."""

    vector_weight = getattr(settings, "RAG_VECTOR_WEIGHT", 0.7)
    websearch_weight = getattr(settings, "RAG_WEBSEARCH_WEIGHT", 0.2)
    trigram_weight = getattr(settings, "RAG_TRIGRAM_WEIGHT", 0.1)
    trigram_floor = getattr(settings, "RAG_TRIGRAM_FLOOR", 0.1)

    if lexical_only:
        vector_weight = 0.0
        total_lexical = websearch_weight + trigram_weight
        if total_lexical <= 0:
            websearch_weight = 1.0
            trigram_weight = 0.0
        else:
            websearch_weight /= total_lexical
            trigram_weight /= total_lexical
    else:
        total_weight = vector_weight + websearch_weight + trigram_weight
        if total_weight <= 0:
            vector_weight = 1.0
            websearch_weight = 0.0
            trigram_weight = 0.0
        else:
            vector_weight /= total_weight
            websearch_weight /= total_weight
            trigram_weight /= total_weight

    base_queryset = Document.objects.filter(company_id=company_id, chatbot_id=chatbot_id)
    if sources:
        base_queryset = base_queryset.filter(source__in=list(sources))

    if connection.vendor == 'sqlite':
        scored_docs = []
        query_phrase = " ".join(query_tokens)
        for doc in base_queryset:
            similarity = _cosine_similarity(doc.embedding, query_embedding) if not lexical_only else 0.0
            websearch_raw = 0.0
            trigram_raw = 0.0
            if query_tokens:
                lowered = (doc.content or "").lower()
                if query_phrase and query_phrase in lowered:
                    occurrences = lowered.count(query_phrase)
                    websearch_raw = float(occurrences * len(query_phrase))
                else:
                    websearch_raw = float(
                        sum(lowered.count(token) for token in query_tokens)
                    )
                trigram_raw = _trigram_similarity(query_phrase or query, lowered)
                if trigram_raw < trigram_floor:
                    trigram_raw = 0.0

            scored_docs.append((doc, similarity, websearch_raw, trigram_raw))

        max_websearch = max((item[2] for item in scored_docs), default=0.0)
        max_trigram = max((item[3] for item in scored_docs), default=0.0)

        enriched = []
        for doc, similarity, websearch_raw, trigram_raw in scored_docs:
            websearch_score = (websearch_raw / max_websearch) if max_websearch > 0 else 0.0
            trigram_score = (trigram_raw / max_trigram) if max_trigram > 0 else 0.0
            lexical_score = (websearch_weight * websearch_score) + (
                trigram_weight * trigram_score
            )
            combined_score = (vector_weight * similarity) + lexical_score
            enriched.append(
                {
                    "doc": doc,
                    "similarity": similarity,
                    "lexical_score": lexical_score,
                    "websearch_score": websearch_score,
                    "trigram_score": trigram_score,
                    "combined_score": combined_score,
                }
            )

        enriched.sort(
            key=lambda item: (
                -item["combined_score"],
                -item["lexical_score"],
                -item["similarity"],
                item["doc"].id,
            )
        )

        rows = enriched[:top_k]

        results: List[Dict[str, object]] = []
        for item in rows:
            display, url, metadata = _document_metadata_for_search(item["doc"])
            results.append(
                {
                    "id": item["doc"].id,
                    "source": item["doc"].source,
                    "source_id": item["doc"].source_id,
                    "source_display": display,
                    "source_url": url,
                    "content": item["doc"].content,
                    "metadata": metadata,
                    "similarity": float(item["similarity"]),
                    "lexical_score": float(item["lexical_score"]),
                    "websearch_score": float(item["websearch_score"]),
                    "trigram_score": float(item["trigram_score"]),
                    "combined_score": float(item["combined_score"]),
                }
            )

        return results

    queryset = base_queryset.annotate(
        distance=CosineDistance("embedding", query_embedding)
    ).annotate(
        similarity=ExpressionWrapper(
            Value(1.0) - F("distance"),
            output_field=FloatField(),
        )
    )

    if query_tokens:
        search_vector = SearchVector("content", config="english")
        search_query = SearchQuery(query, search_type="websearch", config="english")
        queryset = queryset.annotate(
            websearch_rank=Coalesce(SearchRank(search_vector, search_query), Value(0.0)),
            trigram_raw_value=Coalesce(TrigramSimilarity("content", query), Value(0.0)),
        ).annotate(
            trigram_raw=Case(
                When(
                    trigram_raw_value__gte=Value(trigram_floor),
                    then=F("trigram_raw_value"),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            )
        )
    else:
        queryset = queryset.annotate(
            websearch_rank=Value(0.0, output_field=FloatField()),
            trigram_raw_value=Value(0.0, output_field=FloatField()),
            trigram_raw=Value(0.0, output_field=FloatField()),
        )

    queryset = queryset.annotate(
        websearch_max=Window(expression=Max("websearch_rank")),
        trigram_max=Window(expression=Max("trigram_raw")),
    )

    queryset = queryset.annotate(
        websearch_score=ExpressionWrapper(
            Case(
                When(
                    websearch_max__gt=Value(0.0),
                    then=F("websearch_rank")
                    / NullIf(F("websearch_max"), Value(0.0)),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
            output_field=FloatField(),
        ),
        trigram_score=ExpressionWrapper(
            Case(
                When(
                    trigram_max__gt=Value(0.0),
                    then=F("trigram_raw")
                    / NullIf(F("trigram_max"), Value(0.0)),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
            output_field=FloatField(),
        ),
    )

    queryset = queryset.annotate(
        lexical_score=ExpressionWrapper(
            Value(websearch_weight) * F("websearch_score")
            + Value(trigram_weight) * F("trigram_score"),
            output_field=FloatField(),
        )
    )

    similarity_field = Coalesce(F("similarity"), Value(0.0)) if not lexical_only else Value(0.0)

    queryset = queryset.annotate(
        combined_score=ExpressionWrapper(
            Value(vector_weight) * similarity_field
            + F("lexical_score"),
            output_field=FloatField(),
        )
    )

    queryset = queryset.order_by(
        "-combined_score",
        "-lexical_score",
        "-similarity",
        "id",
    )

    rows = queryset[:top_k]

    results: List[Dict[str, object]] = []
    for doc in rows:
        display, url, metadata = _document_metadata_for_search(doc)
        results.append(
            {
                "id": doc.id,
                "source": doc.source,
                "source_id": doc.source_id,
                "source_display": display,
                "source_url": url,
                "content": doc.content,
                "metadata": metadata,
                "similarity": float(doc.similarity) if (doc.similarity is not None and not lexical_only) else 0.0,
                "lexical_score": float(doc.lexical_score) if doc.lexical_score is not None else 0.0,
                "websearch_score": float(doc.websearch_score) if doc.websearch_score is not None else 0.0,
                "trigram_score": float(doc.trigram_score) if doc.trigram_score is not None else 0.0,
                "combined_score": float(doc.combined_score) if doc.combined_score is not None else 0.0,
            }
        )

    return results


def _finalize_search_attempts(
    attempts: Sequence[Dict[str, object]]
) -> Tuple[List[Dict[str, object]], float]:
    """Merge, deduplicate, and normalize search results."""

    if not attempts:
        return [], 0.0

    limit = max(int(attempt.get("top_k", 0) or 0) for attempt in attempts)
    if limit <= 0:
        limit = max(len(attempt.get("documents", [])) for attempt in attempts)

    dedup: Dict[int, Dict[str, object]] = {}
    for attempt in attempts:
        documents = attempt.get("documents") or []
        for doc in documents:
            doc_id = doc.get("id")
            if doc_id is None:
                continue
            candidate = dict(doc)
            existing = dedup.get(doc_id)
            if existing is None or candidate.get("combined_score", 0.0) > existing.get(
                "combined_score", 0.0
            ):
                dedup[doc_id] = candidate

    ranked = sorted(
        dedup.values(),
        key=lambda item: (
            -float(item.get("combined_score", 0.0)),
            -float(item.get("lexical_score", 0.0)),
            -float(item.get("similarity", 0.0)),
            int(item.get("id", 0)),
        ),
    )

    best_score = max((float(item.get("combined_score", 0.0)) for item in ranked), default=0.0)
    for item in ranked:
        if best_score > 0:
            item["normalized_score"] = float(item.get("combined_score", 0.0)) / best_score
        else:
            item["normalized_score"] = 0.0

    if limit <= 0:
        return ranked, best_score

    return ranked[:limit], best_score


def search_documents(
    company_id: int,
    chatbot_id: int,
    query: str,
    top_k: int = 5,
    sources: Optional[Iterable[str]] = None,
    *,
    query_embedding: Optional[Sequence[float]] = None,
    query_tokens: Optional[Sequence[str]] = None,
):
    """Search for relevant documents using vector and lexical signals with fallbacks."""

    if query_embedding is None:
        query_embedding = embed_text(query)
    if query_tokens is None:
        query_tokens = _tokenize_query(query)

    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 1
    if top_k < 1:
        top_k = 1

    primary_documents = _search_documents_single(
        company_id=company_id,
        chatbot_id=chatbot_id,
        query=query,
        top_k=top_k,
        sources=sources,
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        lexical_only=False,
    )

    attempts: List[Dict[str, object]] = [
        {
            "label": "primary",
            "top_k": top_k,
            "documents": primary_documents,
        }
    ]

    merged_primary, primary_best = _finalize_search_attempts(attempts)

    min_score_threshold = float(
        getattr(settings, "RAG_SEARCH_MIN_SCORE", 0.35)
    )

    if primary_best >= min_score_threshold or not merged_primary:
        return merged_primary

    fallback_attempts: List[Dict[str, object]] = []
    fallback_details: List[Dict[str, object]] = []

    expanded_top_k = max(top_k * 2, top_k + 5)
    broadened = _search_documents_single(
        company_id=company_id,
        chatbot_id=chatbot_id,
        query=query,
        top_k=expanded_top_k,
        sources=sources,
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        lexical_only=False,
    )
    fallback_attempts.append({"label": "broaden_top_k", "top_k": expanded_top_k, "documents": broadened})
    fallback_details.append(
        {
            "label": "broaden_top_k",
            "top_k": expanded_top_k,
            "result_count": len(broadened),
            "best_score": max((doc.get("combined_score", 0.0) for doc in broadened), default=0.0),
        }
    )

    if sources:
        widened = _search_documents_single(
            company_id=company_id,
            chatbot_id=chatbot_id,
            query=query,
            top_k=expanded_top_k,
            sources=None,
            query_embedding=query_embedding,
            query_tokens=query_tokens,
            lexical_only=False,
        )
        fallback_attempts.append(
            {"label": "drop_source_filter", "top_k": expanded_top_k, "documents": widened}
        )
        fallback_details.append(
            {
                "label": "drop_source_filter",
                "top_k": expanded_top_k,
                "result_count": len(widened),
                "best_score": max((doc.get("combined_score", 0.0) for doc in widened), default=0.0),
            }
        )

    lexical_top_k = max(expanded_top_k, top_k + 10)
    lexical_only_docs = _search_documents_single(
        company_id=company_id,
        chatbot_id=chatbot_id,
        query=query,
        top_k=lexical_top_k,
        sources=None if sources else sources,
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        lexical_only=True,
    )
    fallback_attempts.append(
        {"label": "lexical_only", "top_k": lexical_top_k, "documents": lexical_only_docs}
    )
    fallback_details.append(
        {
            "label": "lexical_only",
            "top_k": lexical_top_k,
            "result_count": len(lexical_only_docs),
            "best_score": max((doc.get("combined_score", 0.0) for doc in lexical_only_docs), default=0.0),
        }
    )

    attempts.extend(fallback_attempts)
    merged_results, final_best = _finalize_search_attempts(attempts)

    record_retrieval_fallback_event(
        event_type="search_low_score",
        company_id=company_id,
        chatbot_id=chatbot_id,
        query=query,
        improved=final_best > primary_best,
        details={
            "primary_best": primary_best,
            "final_best": final_best,
            "attempts": fallback_details,
        },
    )

    return merged_results


def _extract_json_from_text(text: str) -> Optional[object]:
    if not text:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    code_block_match = re.search(r"```json\s*(.*?)```", stripped, re.DOTALL)
    if code_block_match:
        json_candidate = code_block_match.group(1).strip()
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            return None

    return None


def _call_cross_encoder_reranker(
    model: str,
    query: str,
    candidates: Sequence[dict],
) -> Dict[str, float]:
    if not candidates:
        return {}

    client = get_openai_client()

    formatted_candidates = []
    for candidate in candidates:
        candidate_id = str(candidate.get("doc_id"))
        content = (candidate.get("content") or "").strip()
        metadata = candidate.get("metadata") or {}
        formatted_candidates.append(
            {
                "doc_id": candidate_id,
                "content": content[:4000],
                "metadata": metadata,
            }
        )

    user_payload = json.dumps(
        {
            "query": query,
            "documents": formatted_candidates,
        },
        ensure_ascii=False,
    )

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are a document reranker. Given a JSON payload containing a user query "
                            "and candidate documents, you must assign each candidate a relevance score "
                            "between 0 and 1. Respond strictly with JSON using the schema "
                            "[{\"doc_id\": string, \"score\": number}] with scores in descending order."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_payload,
                    }
                ],
            },
        ],
        temperature=0,
    )

    output_text = getattr(response, "output_text", None)
    if not output_text:
        try:
            parts: List[str] = []
            for item in getattr(response, "output", []):
                for piece in getattr(item, "content", []):
                    if getattr(piece, "type", "") in {"output_text", "text"}:
                        parts.append(getattr(piece, "text", ""))
            output_text = "".join(parts)
        except Exception:  # pragma: no cover - defensive
            output_text = ""

    parsed = _extract_json_from_text(output_text or "")
    if not isinstance(parsed, list):
        raise ValueError("Reranker did not return a JSON array of scores")

    scores: Dict[str, float] = {}
    for entry in parsed:
        if not isinstance(entry, Mapping):
            continue
        doc_id = entry.get("doc_id")
        score = entry.get("score")
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            continue
        if doc_id is not None:
            scores[str(doc_id)] = score_value

    return scores


def _get_cached_rerank_embedding(
    doc_id: Optional[int],
    content: str,
    model: str,
) -> Optional[List[float]]:
    if not doc_id or not content:
        return None

    try:
        document = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return embed_text(content, model=model)

    cache = dict(document.rerank_cache or {})
    cache_key = f"embedding::{model}"
    cached = cache.get(cache_key)
    if isinstance(cached, Mapping):
        vector = cached.get("vector")
        if isinstance(vector, list):
            return vector

    embedding_vector = embed_text(content, model=model)
    cache[cache_key] = {
        "vector": embedding_vector,
        "updated_at": timezone.now().isoformat(),
    }
    Document.objects.filter(id=doc_id).update(rerank_cache=cache)

    return embedding_vector


def rerank_documents(query: str, documents: Sequence[dict]) -> List[dict]:
    """Re-rank documents using a cross-encoder or cached high-fidelity embeddings."""

    if not documents:
        return []

    candidates = list(documents)

    rerank_model = getattr(settings, "OPENAI_RERANK_MODEL", "").strip()
    fallback_model = getattr(settings, "OPENAI_RERANK_EMBEDDING_MODEL", "").strip()
    primary_embedding_model = getattr(settings, "OPENAI_EMBEDDING_MODEL", "").strip()

    if not rerank_model and not fallback_model and primary_embedding_model:
        fallback_model = primary_embedding_model

    top_n_setting = getattr(settings, "RAG_RERANK_TOP_N", 8)
    try:
        top_n = int(top_n_setting)
    except (TypeError, ValueError):
        top_n = 8
    if top_n < 1:
        top_n = 1
    top_n = min(top_n, len(candidates))

    rerank_scores: Dict[str, float] = {}
    alias_lookup: Dict[int, str] = {}
    alias_to_doc_key: Dict[str, str] = {}

    top_slice = candidates[:top_n]

    for idx, doc in enumerate(top_slice):
        doc_id = doc.get("id")
        alias = str(doc_id) if doc_id is not None else f"idx-{idx}"
        alias_lookup[id(doc)] = alias
        alias_to_doc_key[alias] = str(doc_id) if doc_id is not None else alias

    if rerank_model and top_slice:
        payload: List[dict] = []
        for doc in top_slice:
            alias = alias_lookup[id(doc)]
            payload.append(
                {
                    "doc_id": alias,
                    "content": doc.get("content") or "",
                    "metadata": doc.get("metadata") or {},
                }
            )

        try:
            alias_scores = _call_cross_encoder_reranker(
                rerank_model,
                query,
                payload,
            )
            rerank_scores = {
                alias_to_doc_key.get(alias, alias): score
                for alias, score in alias_scores.items()
            }
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception(
                "Cross-encoder reranker '%s' failed; attempting embedding-based fallback",
                rerank_model,
            )
            rerank_scores = {}

    if not rerank_scores and fallback_model and top_slice:
        try:
            query_embedding = embed_text(query, model=fallback_model)
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception(
                "Failed to embed query with high-fidelity model '%s'; retaining original ordering",
                fallback_model,
            )
        else:
            for doc in top_slice:
                doc_id = doc.get("id")
                alias = alias_lookup.get(id(doc)) or (str(doc_id) if doc_id is not None else None)
                content = (doc.get("content") or "").strip()
                if not content or alias is None:
                    continue
                try:
                    if doc_id:
                        doc_embedding = _get_cached_rerank_embedding(doc_id, content, fallback_model)
                    else:
                        doc_embedding = embed_text(content, model=fallback_model)
                except Exception:  # pragma: no cover - defensive fallback
                    logger.exception(
                        "Failed to embed document %s with high-fidelity model '%s'",
                        doc_id,
                        fallback_model,
                    )
                    continue
                if doc_embedding is None:
                    continue
                key = str(doc_id) if doc_id is not None else alias
                rerank_scores[key] = _cosine_similarity(query_embedding, doc_embedding)

    if not rerank_scores:
        reranked: List[dict] = []
        for doc in candidates:
            updated = dict(doc)
            if "rerank_score" not in updated:
                updated["rerank_score"] = None
            reranked.append(updated)
        return reranked

    scored_slice: List[Tuple[dict, float]] = []
    unscored_slice: List[dict] = []
    for doc in top_slice:
        doc_id = doc.get("id")
        key = str(doc_id) if doc_id is not None else alias_lookup.get(id(doc))
        score = rerank_scores.get(key) if key is not None else None
        if score is None:
            unscored_slice.append(doc)
        else:
            scored_slice.append((doc, score))

    scored_slice.sort(key=lambda item: (-item[1], item[0].get("id")))

    reordered = [doc for doc, _ in scored_slice] + unscored_slice + candidates[top_n:]

    reranked: List[dict] = []
    for doc in reordered:
        updated = dict(doc)
        doc_id = doc.get("id")
        key = str(doc_id) if doc_id is not None else alias_lookup.get(id(doc))
        if key is not None and key in rerank_scores:
            updated["rerank_score"] = float(rerank_scores[key])
        else:
            updated["rerank_score"] = None
        reranked.append(updated)

    return reranked
