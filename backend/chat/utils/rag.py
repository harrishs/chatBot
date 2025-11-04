import hashlib
import json
import logging
import re
from collections import Counter, OrderedDict
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from django.utils import timezone

from openai import APIConnectionError, APITimeoutError, RateLimitError
from django.conf import settings
from chat.utils.embeddings import (
    embed_text,
    get_openai_client,
    record_retrieval_fallback_event,
    rerank_documents,
    search_documents,
)


logger = logging.getLogger(__name__)
from chat.models import JiraIssue


_SECRET_KEY_VALUE_PATTERN = re.compile(
    r"(?im)(?P<key>password|secret|token|apikey|api_key|access_key)\s*(?P<sep>[:=])(?P<ws>\s*)(?P<quote>['\"])?"
    r"(?P<value>[^\n'\"]+)(?P=quote)?"
)
_OPENAI_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")
_PEM_BLOCK_PATTERN = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)
_CODE_BLOCK_PATTERN = re.compile(
    r"```(?P<lang>[^\n`]*)((?P<newline>\n)?)(?P<content>.*?)```",
    re.DOTALL,
)
_INLINE_CODE_PATTERN = re.compile(r"`(?P<inline>[^`\n]{1,120})`")

_CODE_BLOCK_LANGUAGE_ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "py": "python",
    "plaintext": "",
    "plain": "",
    "text": "",
    "yml": "yaml",
    "ts": "typescript",
    "ps1": "powershell",
}
_ALLOWED_CODE_BLOCK_LANGUAGES = {
    "",
    "bash",
    "python",
    "javascript",
    "typescript",
    "json",
    "yaml",
    "sql",
    "ini",
    "toml",
    "html",
    "css",
    "go",
    "java",
    "kotlin",
    "c",
    "cpp",
    "powershell",
}
_MAX_CODE_BLOCK_LINES = 12
_MAX_CODE_BLOCK_CHARACTERS = 600

_MAX_METADATA_SNIPPET_CHARACTERS = 1200
_LOW_CONFIDENCE_THRESHOLD = 0.45
_LOW_CONFIDENCE_DRAFT_COUNT = 3
_UNCERTAINTY_PHRASES = {
    "i don't know",
    "i do not know",
    "cannot find",
    "can't find",
    "not sure",
    "no information",
    "i'm not sure",
}
_REFUSAL_PHRASES = {
    "i cannot help with",
    "i can't help with",
    "i cannot assist",
    "i can't assist",
}
_CITATION_TOKEN_PATTERN = re.compile(r"\[[A-Za-z0-9_.:-]+:[^\[\]]+\]")


_QUERY_REWRITE_CACHE: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
_MAX_QUERY_REWRITE_CACHE_SIZE = 128


def _plan_retrieval_sources(
    query: str, history: Optional[List[Dict[str, str]]] = None
) -> List[List[str]]:
    """Return prioritized source groups based on ``query`` and optional ``history``."""

    if not query and not history:
        return []

    recent_user_messages: List[str] = []
    if history:
        for turn in history[-3:]:
            user_message = (turn.get("user") or "").strip()
            if user_message:
                recent_user_messages.append(user_message)

    combined_text = " ".join(
        part for part in ([query] + recent_user_messages) if part
    )
    normalized = combined_text.lower()

    source_plan: List[List[str]] = []

    def _append_plan(sources: Sequence[str]) -> None:
        normalized_sources = [source for source in sources if source]
        if not normalized_sources:
            return
        if normalized_sources not in source_plan:
            source_plan.append(list(normalized_sources))

    jira_keywords = {
        "jira",
        "ticket",
        "tickets",
        "epic",
        "epics",
        "story",
        "stories",
        "sprint",
        "backlog",
    }

    confluence_keywords = {
        "confluence",
        "wiki",
        "knowledge base",
        "kb article",
        "runbook",
        "playbook",
    }

    github_keywords = {
        "github",
        "pull request",
        "merge request",
        "commit",
        "branch",
        "repository",
        "repo",
        "code review",
    }

    feedback_keywords = {
        "feedback",
        "review",
        "reviews",
        "rating",
        "ratings",
        "complaint",
        "complaints",
        "praise",
        "satisfaction",
    }

    jira_key_pattern = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

    if normalized:
        if any(keyword in normalized for keyword in jira_keywords) or jira_key_pattern.search(
            combined_text
        ):
            _append_plan(["jira_issue", "jira_comment"])

        if any(keyword in normalized for keyword in confluence_keywords):
            _append_plan(["confluence"])

        if any(keyword in normalized for keyword in github_keywords):
            _append_plan(["github"])

        if any(keyword in normalized for keyword in feedback_keywords):
            _append_plan(["feedback"])

    return source_plan


def _redacted_secret_value(match: re.Match) -> str:
    quote = match.group("quote") or ""
    ws = match.group("ws") or " "
    return f"{match.group('key')}{match.group('sep')}{ws}{quote}[redacted sensitive data]{quote}"


def _truncate_text(value: str, max_length: int) -> str:
    """Return ``value`` trimmed to ``max_length`` characters with ellipsis when needed."""
    if not value:
        return ""

    value = value.strip()
    if len(value) <= max_length:
        return value

    truncated = value[:max_length].rstrip()
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.6:
        truncated = truncated[:last_space]

    return truncated.rstrip(" \\n") + "…"


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "have",
    "using",
    "into",
    "your",
    "about",
    "https",
    "http",
    "com",
    "org",
    "true",
    "false",
    "none",
    "null",
    "name",
    "private",
    "version",
    "module",
    "type",
    "default",
    "file",
    "files",
    "config",
    "configuration",
    "example",
    "copy",
    "backend",
    "frontend",
    "service",
    "services",
    "environment",
    "variables",
    "variable",
    "docker",
    "compose",
    "prod",
    "production",
    "development",
    "requirement",
    "requirements",
    "package",
    "packages",
    "json",
    "txt",
    "env",
    "line",
    "lines",
    "data",
    "value",
    "values",
}


def _extract_keywords(content: str, limit: int = 12) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_+.\-]+", content.lower())
    filtered = [
        token
        for token in tokens
        if len(token) > 2 and token not in _STOPWORDS and any(char.isalpha() for char in token)
    ]

    if not filtered:
        return []

    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(limit)]


def _condense_whitespace(value: str) -> str:
    """Collapse consecutive whitespace into single spaces while preserving newlines."""

    if not value:
        return ""

    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in normalized_lines if line)


def _build_excerpt(content: str, max_length: int = 600) -> str:
    """Return a sanitized excerpt constructed from the first informative paragraphs."""

    if not content:
        return ""

    paragraphs = re.split(r"\n\s*\n", content)
    excerpt_parts: List[str] = []
    consumed = 0

    for paragraph in paragraphs:
        sanitized = _condense_whitespace(
            re.sub(r"```.*?```", " ", paragraph, flags=re.DOTALL)
        ).strip()
        if not sanitized:
            continue

        separator = 2 if excerpt_parts else 0
        projected = consumed + len(sanitized) + separator

        if projected > max_length and consumed:
            remaining = max_length - consumed - separator
            if remaining > 0:
                excerpt_parts.append(_truncate_text(sanitized, remaining))
            break

        if projected > max_length:
            excerpt_parts.append(_truncate_text(sanitized, max_length))
            break

        excerpt_parts.append(sanitized)
        consumed = projected

        if consumed >= max_length:
            break

    excerpt = "\n\n".join(excerpt_parts).strip()
    return excerpt


def _redact_sensitive_snippet(value: str) -> str:
    """Redact sensitive tokens from ``value`` while preserving other content."""

    if not value:
        return ""

    sanitized = value
    sanitized = _SECRET_KEY_VALUE_PATTERN.sub(_redacted_secret_value, sanitized)
    sanitized = _OPENAI_KEY_PATTERN.sub("[redacted sensitive data]", sanitized)
    sanitized = _PEM_BLOCK_PATTERN.sub("[redacted sensitive data]", sanitized)

    return sanitized.strip("\n")


def _limit_snippet(value: str, max_length: int = _MAX_METADATA_SNIPPET_CHARACTERS) -> str:
    """Return ``value`` trimmed to ``max_length`` characters with ellipsis when needed."""

    if not value:
        return ""

    if len(value) <= max_length:
        return value

    truncated = value[:max_length].rstrip()
    return f"{truncated}…"


def _metadata_from_document(document: Dict) -> Dict:
    """Convert a search document into safe metadata for prompts and responses."""

    stored_metadata = document.get("metadata") or {}

    raw_chunk_text = stored_metadata.get("chunk_text")
    if raw_chunk_text is None:
        raw_chunk_text = document.get("content") or ""

    sanitized_chunk = _redact_sensitive_snippet(raw_chunk_text)
    snippet = _limit_snippet(sanitized_chunk)

    lines = [line.strip() for line in sanitized_chunk.splitlines() if line.strip()]
    title = stored_metadata.get("title") or (lines[0][:120] if lines else "")

    summary_lines: List[str] = []
    if lines:
        summary_lines.extend(lines[:8])

        important_prefixes = ("Resolved at", "Completion summary")
        for line in lines[8:]:
            if line.startswith(important_prefixes) and line not in summary_lines:
                summary_lines.append(line)

    summary_source = " ".join(summary_lines) if summary_lines else ""
    summary = _truncate_text(summary_source, 320)
    excerpt = _build_excerpt(sanitized_chunk)

    metadata = {
        key: document.get(key)
        for key in (
            "id",
            "source",
            "source_id",
            "source_display",
            "similarity",
        )
        if document.get(key) is not None
    }

    for score_key in (
        "combined_score",
        "lexical_score",
        "websearch_score",
        "trigram_score",
        "normalized_score",
        "rerank_score",
    ):
        value = document.get(score_key)
        if isinstance(value, (int, float)):
            metadata[score_key] = float(value)

    source_url = stored_metadata.get("source_url") or document.get("source_url")
    if source_url:
        metadata["source_url"] = source_url

    if title:
        metadata["title"] = title
    if summary:
        metadata["summary"] = summary
    if excerpt:
        metadata["excerpt"] = excerpt
    if sanitized_chunk:
        metadata["chunk_text"] = sanitized_chunk
    if snippet:
        metadata["snippet"] = snippet

    def _coerce_int(value: object) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    for key in ("chunk_index", "chunk_count", "chunk_tokens", "chunk_char_count"):
        coerced = _coerce_int(stored_metadata.get(key))
        if coerced is not None:
            metadata[key] = coerced

    for key in ("path", "space_key", "section_heading"):
        value = stored_metadata.get(key)
        if value not in (None, ""):
            metadata[key] = value

    keyword_source = summary or summary_source
    keywords = _extract_keywords(keyword_source) if keyword_source else []
    if keywords:
        metadata["keywords"] = ", ".join(keywords)

    return metadata


def _metadata_citation_label(metadata: Dict[str, Any]) -> str:
    """Return a standardized citation label for ``metadata``."""

    label_identifier = metadata.get("source_display") or metadata.get("source_id") or "unknown"
    label_source = metadata.get("source") or "source"
    return f"[{label_source}:{label_identifier}]"


def _format_metadata_for_prompt(metadata: Dict) -> str:
    """Format metadata for inclusion in the LLM prompt."""

    lines: List[str] = [_metadata_citation_label(metadata)]

    detail_lines: List[str] = []

    def _append_detail(label: str, value: object) -> None:
        if value in (None, ""):
            return
        detail_lines.append(f"- {label}: {value}")

    title = metadata.get("title")
    if title:
        _append_detail("Title", title)

    section_heading = metadata.get("section_heading")
    if section_heading and section_heading != title:
        _append_detail("Section", section_heading)

    path = metadata.get("path")
    if path:
        _append_detail("Path", path)

    space_key = metadata.get("space_key")
    if space_key:
        _append_detail("Space", space_key)

    chunk_index = metadata.get("chunk_index")
    chunk_count = metadata.get("chunk_count")
    if isinstance(chunk_index, int) and isinstance(chunk_count, int):
        _append_detail("Chunk", f"{chunk_index + 1} of {chunk_count}")
    elif isinstance(chunk_index, int):
        _append_detail("Chunk index", chunk_index)

    summary = metadata.get("summary")
    if summary and summary != title:
        _append_detail("Summary", summary)

    source_url = metadata.get("source_url")
    if source_url:
        _append_detail("URL", source_url)

    similarity = metadata.get("similarity")
    if isinstance(similarity, float):
        _append_detail("Similarity", f"{similarity:.3f}")

    keywords = metadata.get("keywords")
    if keywords:
        _append_detail("Keywords", keywords)

    chunk_tokens = metadata.get("chunk_tokens")
    if isinstance(chunk_tokens, int) and chunk_tokens > 0:
        _append_detail("Chunk tokens", chunk_tokens)

    chunk_char_count = metadata.get("chunk_char_count")
    if isinstance(chunk_char_count, int) and chunk_char_count > 0:
        _append_detail("Chunk characters", chunk_char_count)

    if detail_lines:
        lines.append("Metadata:")
        lines.extend(detail_lines)

    snippet = metadata.get("snippet") or metadata.get("chunk_text") or metadata.get("excerpt")
    if snippet:
        if detail_lines:
            lines.append("")
        lines.append("Snippet:")
        lines.append(snippet)

    return "\n".join(lines)


def _summarize_metadata_entries(
    metadata_entries: Sequence[Dict[str, Any]],
) -> List[str]:
    """Return compact research notes derived from ``metadata_entries``.

    The routine applies lightweight heuristics to surface the key claim for each
    entry while preserving the original citation label.
    """

    notes: List[str] = []
    seen_labels: Set[str] = set()

    for metadata in metadata_entries:
        citation_label = _metadata_citation_label(metadata)

        if citation_label in seen_labels:
            continue

        seen_labels.add(citation_label)

        title = (metadata.get("title") or "").strip()
        summary = (metadata.get("summary") or "").strip()
        snippet = (
            metadata.get("snippet")
            or metadata.get("chunk_text")
            or metadata.get("excerpt")
            or ""
        ).strip()

        def _normalize(text: str) -> str:
            if not text:
                return ""
            # Remove fenced code indicators and compress whitespace.
            text = re.sub(r"```+", "", text)
            text = re.sub(r"`([^`]+)`", r"\1", text)
            text = re.sub(r"\s+", " ", text)
            return text.strip()

        candidate = _normalize(summary)

        if not candidate:
            candidate = _normalize(snippet)

        if not candidate and title:
            candidate = title

        keywords = metadata.get("keywords")
        if not candidate and keywords:
            candidate = f"Keywords: {keywords}"

        status = metadata.get("status")
        resolution = metadata.get("resolution")
        if metadata.get("source") == "jira" and status and not candidate:
            status_line = f"Status {status}".strip()
            if resolution:
                status_line = f"Status {status}, resolution {resolution}"
            candidate = status_line

        if not candidate:
            candidate = "No additional summary available."

        if title and candidate != title and not candidate.lower().startswith(title.lower()):
            note_body = f"{title}: {candidate}"
        else:
            note_body = candidate

        note_body = _truncate_text(note_body, 240)

        notes.append(f"- {note_body} {citation_label}")

    return notes


def _collect_citations(metadata_list: List[Dict]) -> List[str]:
    """Return the list of citation tokens derived from metadata entries."""

    citations: List[str] = []
    for metadata in metadata_list:
        label_identifier = metadata.get("source_display") or metadata.get("source_id")
        label_source = metadata.get("source")
        if not label_source or not label_identifier:
            continue
        token = f"[{label_source}:{label_identifier}]"
        if token not in citations:
            citations.append(token)
    return citations


def _extract_answer_citations(answer: str) -> List[str]:
    """Return all citation tokens that appear in ``answer``."""

    if not answer:
        return []

    return _CITATION_TOKEN_PATTERN.findall(answer)


def _rewrite_cache_key(company_id: int, chatbot_id: int, query: str) -> str:
    source = f"{company_id}:{chatbot_id}:{query.strip().lower()}".encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def _get_cached_rewrites(company_id: int, chatbot_id: int, query: str) -> Optional[List[str]]:
    cache_key = _rewrite_cache_key(company_id, chatbot_id, query)
    cached = _QUERY_REWRITE_CACHE.get(cache_key)
    if not cached:
        return None

    cached["timestamp"] = timezone.now()
    _QUERY_REWRITE_CACHE.move_to_end(cache_key)
    return list(cached.get("rewrites", []))


def _store_rewrites(
    company_id: int,
    chatbot_id: int,
    query: str,
    rewrites: Sequence[str],
) -> None:
    cache_key = _rewrite_cache_key(company_id, chatbot_id, query)
    _QUERY_REWRITE_CACHE[cache_key] = {
        "timestamp": timezone.now(),
        "rewrites": list(rewrites),
    }
    while len(_QUERY_REWRITE_CACHE) > _MAX_QUERY_REWRITE_CACHE_SIZE:
        _QUERY_REWRITE_CACHE.popitem(last=False)


def _parse_rewrite_suggestions(
    text: str, original_query: str, limit: int
) -> List[str]:
    if not text:
        return []

    suggestions: List[str] = []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, str):
                cleaned = entry.strip()
                if cleaned and cleaned.lower() != original_query.lower():
                    suggestions.append(cleaned)

    if not suggestions:
        for raw_line in text.splitlines():
            cleaned_line = re.sub(r"^[\s\-\*\d\.)]+", "", raw_line).strip()
            if cleaned_line and cleaned_line.lower() != original_query.lower():
                suggestions.append(cleaned_line)

    unique: List[str] = []
    seen = set()
    for suggestion in suggestions:
        key = suggestion.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(suggestion)
        if len(unique) >= limit:
            break

    return unique


def _suggest_query_rewrites(
    company_id: int,
    chatbot_id: int,
    query: str,
    documents: Sequence[dict],
    *,
    max_suggestions: int = 3,
) -> Tuple[List[str], bool]:
    cached = _get_cached_rewrites(company_id, chatbot_id, query)
    if cached:
        return cached, True

    model_name = getattr(settings, "RAG_QUERY_REWRITE_MODEL", "gpt-4o-mini").strip()
    if not model_name:
        return [], False

    client = get_openai_client()

    context_chunks: List[str] = []
    for doc in list(documents)[:3]:
        metadata = doc.get("metadata") or {}
        title = metadata.get("title") or doc.get("source_display") or doc.get("source_id")
        snippet = metadata.get("chunk_text") or doc.get("content") or ""
        snippet = _truncate_text(_condense_whitespace(snippet), 220)
        if title and snippet:
            context_chunks.append(f"- {title}: {snippet}")
        elif snippet:
            context_chunks.append(f"- {snippet}")

    user_lines = [
        "The initial document search returned low-confidence matches.",
        f"Original question: {query}",
    ]
    if context_chunks:
        user_lines.append("Observed snippets:")
        user_lines.extend(context_chunks)
    user_lines.append(
        "Propose alternative search queries using synonyms or specific terminology. "
        "Respond with a JSON array of short strings."
    )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You refine enterprise search queries. Provide concise alternative "
                        "queries that could retrieve better matches."
                    ),
                },
                {"role": "user", "content": "\n".join(user_lines)},
            ],
            temperature=0.2,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Query rewrite request failed: %s", exc)
        return [], False

    choices = getattr(response, "choices", []) or []
    message = getattr(choices[0], "message", None) if choices else None
    text = getattr(message, "content", "") if message else ""

    rewrites = _parse_rewrite_suggestions(text, query, max_suggestions)
    if rewrites:
        _store_rewrites(company_id, chatbot_id, query, rewrites)

    return rewrites, False


def _merge_document_lists(primary: Sequence[dict], additional: Sequence[dict]) -> List[dict]:
    merged: Dict[Tuple[Optional[int], Optional[str]], Dict[str, object]] = {}

    def _doc_key(doc: Dict) -> Tuple[Optional[int], Optional[str]]:
        return (doc.get("id"), doc.get("source_id"))

    for source_docs in (primary, additional):
        for doc in source_docs:
            key = _doc_key(doc)
            candidate = dict(doc)
            existing = merged.get(key)
            if existing is None or candidate.get("combined_score", 0.0) > existing.get(
                "combined_score", 0.0
            ):
                merged[key] = candidate

    merged_list = list(merged.values())
    merged_list.sort(
        key=lambda item: (
            -float(item.get("combined_score", 0.0)),
            -float(item.get("lexical_score", 0.0)),
            -float(item.get("similarity", 0.0)),
            (item.get("id") or 0),
        )
    )

    best_score = max((float(doc.get("combined_score", 0.0)) for doc in merged_list), default=0.0)
    for doc in merged_list:
        if best_score > 0:
            doc["normalized_score"] = float(doc.get("combined_score", 0.0)) / best_score
        else:
            doc["normalized_score"] = 0.0

    return merged_list


def _maybe_expand_with_query_rewrites(
    company_id: int,
    chatbot_id: int,
    query: str,
    top_k: int,
    documents: Sequence[dict],
) -> Tuple[Sequence[dict], Optional[Dict[str, object]]]:
    if not documents:
        base_best = 0.0
    else:
        base_best = max((float(doc.get("combined_score", 0.0)) for doc in documents), default=0.0)

    max_suggestions = int(getattr(settings, "RAG_QUERY_REWRITE_SUGGESTIONS", 3)) or 3
    rewrites, from_cache = _suggest_query_rewrites(
        company_id,
        chatbot_id,
        query,
        documents,
        max_suggestions=max_suggestions,
    )

    if not rewrites:
        return documents, None

    expanded_docs: List[dict] = []
    for rewrite in rewrites:
        rewrite_results = search_documents(
            company_id=company_id,
            chatbot_id=chatbot_id,
            query=rewrite,
            top_k=max(top_k, len(documents) or top_k),
        )
        for doc in rewrite_results:
            candidate = dict(doc)
            candidate.setdefault("query_rewrite", rewrite)
            expanded_docs.append(candidate)

    combined_documents = _merge_document_lists(documents, expanded_docs)
    final_best = max(
        (float(doc.get("combined_score", 0.0)) for doc in combined_documents),
        default=0.0,
    )

    record_retrieval_fallback_event(
        event_type="query_rewrite",
        company_id=company_id,
        chatbot_id=chatbot_id,
        query=query,
        improved=final_best > base_best,
        details={
            "rewrites": rewrites,
            "from_cache": from_cache,
            "base_best": base_best,
            "final_best": final_best,
        },
    )

    return combined_documents, {
        "rewrites": rewrites,
        "from_cache": from_cache,
        "base_best": base_best,
        "final_best": final_best,
    }


def _compute_retrieval_confidence(documents: Sequence[dict]) -> float:
    """Estimate a retrieval confidence score from ranked documents."""

    if not documents:
        return 0.0

    scores: List[float] = []
    for document in documents:
        for key in (
            "normalized_score",
            "combined_score",
            "similarity",
            "rerank_score",
        ):
            value = document.get(key)
            if isinstance(value, (int, float)):
                scores.append(float(value))
                break

    if not scores:
        return 0.0

    top_scores = sorted(scores, reverse=True)[:2]
    blended = top_scores[0]
    if len(top_scores) > 1:
        blended = (0.7 * top_scores[0]) + (0.3 * top_scores[1])

    return max(0.0, min(1.0, float(blended)))


def _evaluate_answer_draft(
    answer: str,
    metadata_list: List[Dict],
    retrieval_confidence: float,
) -> Dict:
    """Score an answer draft based on citation quality and uncertainty signals."""

    found_citations = _extract_answer_citations(answer)
    valid_tokens = set(_collect_citations(metadata_list))
    valid_citations = [token for token in found_citations if token in valid_tokens]
    invalid_citations = [token for token in found_citations if token not in valid_tokens]

    normalized_answer = (answer or "").lower()
    contains_uncertainty = any(phrase in normalized_answer for phrase in _UNCERTAINTY_PHRASES)
    contains_refusal = any(phrase in normalized_answer for phrase in _REFUSAL_PHRASES)

    coverage_target = max(1, min(len(valid_tokens), 3)) if valid_tokens else 0
    unique_valid = len({token for token in valid_citations})
    coverage_ratio = (unique_valid / coverage_target) if coverage_target else 0.0

    score = retrieval_confidence
    if valid_citations:
        score += 0.6 + (0.4 * min(1.0, coverage_ratio))
    else:
        score -= 0.7

    if invalid_citations:
        score -= 0.4 * len(invalid_citations)

    if contains_uncertainty or contains_refusal:
        score -= 0.8

    return {
        "score": float(score),
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
        "found_citations": found_citations,
        "coverage": coverage_ratio,
        "contains_uncertainty": contains_uncertainty,
        "contains_refusal": contains_refusal,
    }


def _judge_answer_drafts(
    question: str,
    metadata_entries: Sequence[Dict[str, Any]],
    drafts: Sequence[Dict[str, Any]],
    *,
    model_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Use an LLM judge to rank answer drafts and suggest rewrites."""

    if len(drafts) < 2:
        return None

    model_choice = model_name or getattr(settings, "RAG_DRAFT_JUDGE_MODEL", "gpt-4o-mini")
    if not model_choice:
        return None

    client = get_openai_client()

    research_notes = _summarize_metadata_entries(metadata_entries)
    context_text = (
        "\n".join(research_notes)
        if research_notes
        else "No supporting metadata was retrieved."
    )

    draft_descriptions: List[str] = []
    for draft in drafts:
        index = draft.get("index")
        answer = draft.get("answer") or ""
        draft_descriptions.append(f"Draft {index}:\n{answer}".strip())

    judge_instructions = (
        "You are an impartial judge tasked with ranking assistant answers."
        " Consider citation usage, correctness, helpfulness, and alignment with the provided metadata."
        " Score each draft between 0 and 1 (higher is better)."
        " If none are satisfactory, you may still rank them but give lower scores."
        " Optionally propose how the answer could be improved in a succinct rewrite suggestion."
        " Respond ONLY in JSON with the following shape:"
        " {\"rankings\": [{\"index\": <draft index>, \"score\": <0-1 float>,"
        " \"feedback\": <optional string>}...], \"rewrite\": <optional string>}"
        " Sorted rankings must list the best draft first."
    )

    judge_prompt = (
        f"Question:\n{question}\n\n"
        f"Metadata research notes:\n{context_text}\n\n"
        f"Candidate drafts:\n\n" + "\n\n".join(draft_descriptions)
    )

    try:
        response = client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": judge_instructions},
                {"role": "user", "content": judge_prompt},
            ],
            temperature=0.0,
        )
    except RateLimitError as exc:
        raise RuntimeError("OpenAI rate limit exceeded while judging drafts") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError("Failed to reach OpenAI while judging drafts") from exc

    response_choices = list(getattr(response, "choices", []) or [])
    if not response_choices:
        return None

    first_choice = response_choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", "") if message else ""
    if not content:
        return None

    parsed: Optional[Dict[str, Any]]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if not isinstance(parsed, dict):
        return None

    rankings_raw = parsed.get("rankings")
    normalized_rankings: List[Dict[str, Any]] = []
    if isinstance(rankings_raw, list):
        for entry in rankings_raw:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if not isinstance(index, int) or not (0 <= index < len(drafts)):
                continue
            score = entry.get("score")
            try:
                score_value = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_value = None
            normalized_entry: Dict[str, Any] = {"index": index}
            if score_value is not None:
                normalized_entry["score"] = max(0.0, min(1.0, score_value))
            feedback = entry.get("feedback")
            if isinstance(feedback, str) and feedback.strip():
                normalized_entry["feedback"] = feedback.strip()
            normalized_rankings.append(normalized_entry)

    if not normalized_rankings:
        return None

    normalized_rankings.sort(key=lambda item: item.get("score", -1.0), reverse=True)

    result: Dict[str, Any] = {"rankings": normalized_rankings}
    rewrite = parsed.get("rewrite") or parsed.get("suggested_rewrite")
    if isinstance(rewrite, str) and rewrite.strip():
        result["rewrite"] = rewrite.strip()

    return result


def _consensus_from_drafts(
    question: str,
    metadata_entries: Sequence[Dict[str, Any]],
    drafts: Sequence[Dict[str, Any]],
    *,
    judge_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Derive a consensus-backed draft selection or fall back to an LLM judge."""

    if len(drafts) < 2:
        return None

    citation_sets: List[Tuple[Dict[str, Any], Set[str]]] = []
    for draft in drafts:
        citations = {
            citation
            for citation in draft.get("citations") or []
            if isinstance(citation, str) and citation
        }
        if citations:
            citation_sets.append((draft, citations))

    consensus_citations: Set[str] = set()
    if citation_sets:
        frequency: Counter[str] = Counter()
        for _, citations in citation_sets:
            frequency.update(citations)

        if frequency:
            majority_threshold = max(2, (len(drafts) // 2) + 1)
            consensus_citations = {
                citation for citation, count in frequency.items() if count >= majority_threshold
            }

            if not consensus_citations:
                top_frequency = max(frequency.values())
                if top_frequency > 1:
                    consensus_citations = {
                        citation
                        for citation, count in frequency.items()
                        if count == top_frequency
                    }

    if consensus_citations:
        best_candidate: Optional[Dict[str, Any]] = None
        best_overlap = -1
        best_score = float("-inf")

        for draft, citations in citation_sets:
            overlap = len(citations & consensus_citations)
            if overlap <= 0:
                continue

            score = float(draft.get("score", 0.0) or 0.0)
            if overlap > best_overlap or (overlap == best_overlap and score > best_score):
                best_candidate = draft
                best_overlap = overlap
                best_score = score

        if best_candidate is not None:
            return {
                "index": best_candidate.get("index"),
                "method": "consensus_citations",
                "consensus_citations": sorted(consensus_citations),
            }

    if judge_fn is None:
        return None

    try:
        judge_details = judge_fn()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Draft judge failed during consensus: %s", exc, exc_info=True)
        return {"method": "heuristic_citation_scoring", "judge_error": str(exc)}

    if not judge_details:
        return None

    top_entry = next(
        (
            entry
            for entry in judge_details.get("rankings", [])
            if isinstance(entry, dict) and isinstance(entry.get("index"), int)
        ),
        None,
    )

    if top_entry is None:
        return {"method": "llm_judge", "judge": judge_details}

    return {
        "index": top_entry.get("index"),
        "method": "llm_judge",
        "judge": judge_details,
    }


def _redact_sensitive_tokens(value: str) -> str:
    """Redact known sensitive token patterns within ``value``."""

    value = _SECRET_KEY_VALUE_PATTERN.sub(_redacted_secret_value, value)
    value = _OPENAI_KEY_PATTERN.sub("[redacted sensitive data]", value)
    value = _PEM_BLOCK_PATTERN.sub("[redacted sensitive data]", value)
    return value


def _sanitize_answer(answer: str, metadata_list: List[Dict]) -> str:
    """Remove unsafe snippets while preserving legitimate technical explanations."""

    sanitized = answer or ""

    def _sanitize_free_text(value: str) -> str:
        """Redact free text while preserving inline code snippets."""

        if not value:
            return value

        segments: List[Dict[str, Any]] = []
        last_end = 0

        for inline in _INLINE_CODE_PATTERN.finditer(value):
            prefix = value[last_end : inline.start()]
            if prefix:
                sanitized_prefix = _redact_sensitive_tokens(prefix)
                if sanitized_prefix:
                    segments.append({"text": sanitized_prefix, "is_inline": False})

            inline_content = inline.group("inline") or ""
            sanitized_inline = _redact_sensitive_tokens(inline_content)
            segments.append({"text": sanitized_inline, "is_inline": True})
            last_end = inline.end()

        remainder = value[last_end:]
        if remainder:
            sanitized_remainder = _redact_sensitive_tokens(remainder)
            if sanitized_remainder:
                segments.append({"text": sanitized_remainder, "is_inline": False})

        if not segments:
            return _redact_sensitive_tokens(value)

        def _replace_range_in_segments(
            items: List[Dict[str, Any]], start: int, end: int, replacement: str
        ) -> List[Dict[str, Any]]:
            if start >= end:
                return items

            new_items: List[Dict[str, Any]] = []
            current = 0
            pending_replacement = replacement

            for segment in items:
                text = segment["text"]
                length = len(text)
                seg_start = current
                seg_end = current + length

                if seg_end <= start or seg_start >= end:
                    new_items.append(segment)
                else:
                    before_len = max(0, start - seg_start)
                    if before_len:
                        new_items.append(
                            {"text": text[:before_len], "is_inline": segment["is_inline"]}
                        )

                    if pending_replacement:
                        new_items.append({"text": pending_replacement, "is_inline": False})
                        pending_replacement = ""

                    after_len = max(0, seg_end - end)
                    if after_len:
                        new_items.append(
                            {"text": text[length - after_len :], "is_inline": segment["is_inline"]}
                        )

                current = seg_end

            if pending_replacement:
                new_items.append({"text": pending_replacement, "is_inline": False})

            return new_items

        def _match_spans_multiple_segments(
            items: List[Dict[str, Any]], start: int, end: int
        ) -> bool:
            current = 0
            first_index: Optional[int] = None

            for index, segment in enumerate(items):
                length = len(segment["text"])
                seg_start = current
                seg_end = current + length
                current = seg_end

                if length == 0:
                    continue

                if first_index is None and seg_start <= start < seg_end:
                    first_index = index

                if seg_start < end <= seg_end:
                    if first_index is None:
                        return False
                    return index != first_index

            return False

        def _apply_pattern_across_segments(
            items: List[Dict[str, Any]], pattern: re.Pattern, replacement_func: Callable[[re.Match], str]
        ) -> List[Dict[str, Any]]:
            combined = "".join(segment["text"] for segment in items)
            search_start = 0

            while True:
                match = pattern.search(combined, search_start)
                if not match:
                    break

                if "[redacted sensitive data]" in match.group(0):
                    search_start = match.end()
                    continue

                if not _match_spans_multiple_segments(items, match.start(), match.end()):
                    search_start = match.end()
                    continue

                replacement = replacement_func(match)
                if replacement == match.group(0):
                    search_start = match.end()
                    continue

                items = _replace_range_in_segments(items, match.start(), match.end(), replacement)
                combined = "".join(segment["text"] for segment in items)
                search_start = match.start() + len(replacement)

            return items

        segments = _apply_pattern_across_segments(
            segments, _SECRET_KEY_VALUE_PATTERN, _redacted_secret_value
        )
        segments = _apply_pattern_across_segments(
            segments, _OPENAI_KEY_PATTERN, lambda _: "[redacted sensitive data]"
        )
        segments = _apply_pattern_across_segments(
            segments, _PEM_BLOCK_PATTERN, lambda _: "[redacted sensitive data]"
        )

        parts: List[str] = []
        for segment in segments:
            text = segment["text"]
            if not text:
                continue
            if segment["is_inline"]:
                parts.append(f"`{text}`")
            else:
                parts.append(text)

        return "".join(parts)

    def _sanitize_code_block(match: re.Match) -> str:
        raw_language = (match.group("lang") or "").strip()
        normalized_language = raw_language.lower()
        normalized_language = _CODE_BLOCK_LANGUAGE_ALIASES.get(
            normalized_language, normalized_language
        )
        if normalized_language not in _ALLOWED_CODE_BLOCK_LANGUAGES:
            language = ""
        else:
            language = normalized_language

        content = match.group("content") or ""
        cleaned_content = _redact_sensitive_tokens(content).strip("\n")

        lines = cleaned_content.splitlines()
        truncated = cleaned_content
        was_truncated = False

        if len(lines) > _MAX_CODE_BLOCK_LINES:
            truncated = "\n".join(lines[:_MAX_CODE_BLOCK_LINES])
            was_truncated = True

        if len(truncated) > _MAX_CODE_BLOCK_CHARACTERS:
            truncated = truncated[:_MAX_CODE_BLOCK_CHARACTERS].rstrip()
            was_truncated = True

        if was_truncated and truncated:
            truncated = f"{truncated}\n…"

        cleaned_content = truncated

        newline = "\n" if cleaned_content else ""
        return f"```{language}{newline}{cleaned_content}```"

    parts: List[str] = []
    last_end = 0
    has_blocks = False
    for block in _CODE_BLOCK_PATTERN.finditer(sanitized):
        has_blocks = True
        prefix = sanitized[last_end : block.start()]
        if prefix:
            parts.append(_sanitize_free_text(prefix))
        parts.append(_sanitize_code_block(block))
        last_end = block.end()

    remainder = sanitized[last_end:]
    if has_blocks:
        if remainder:
            parts.append(_sanitize_free_text(remainder))
        sanitized = "".join(parts)
    else:
        sanitized = _sanitize_free_text(sanitized)

    citations = _collect_citations(metadata_list)
    if citations and not any(token in sanitized for token in citations):
        sanitized = sanitized.rstrip()
        if sanitized:
            sanitized += "\n\n"
        sanitized += "Sources: " + ", ".join(citations)

    return sanitized.strip()


_LATEST_RESOLVED_KEYWORDS = {
    "last",
    "latest",
    "most recent",
}


def _is_latest_resolved_issue_query(query: str) -> bool:
    """Return ``True`` when ``query`` asks for the latest resolved/closed ticket."""

    if not query:
        return False

    normalized = query.lower()

    if not any(keyword in normalized for keyword in _LATEST_RESOLVED_KEYWORDS):
        return False

    if not any(term in normalized for term in ("resolved", "closed")):
        return False

    if not any(term in normalized for term in ("ticket", "issue")):
        return False

    return True


def answer_latest_resolved_issue(company_id: int, chatbot_id: int) -> dict:
    """Return a concise answer describing the most recently resolved Jira issue."""

    issue = (
        JiraIssue.objects.filter(
            sync__chatBot__company_id=company_id,
            sync__chatBot_id=chatbot_id,
            resolution_date__isnull=False,
        )
        .order_by("-resolution_date", "-updated_at")
        .select_related("sync__chatBot")
        .first()
    )

    if not issue:
        return {
            "answer": "I could not find any resolved Jira issues for this chatbot.",
            "sources": [],
        }

    resolved_at = issue.resolution_date
    if resolved_at is not None:
        resolved_at = timezone.localtime(resolved_at) if timezone.is_aware(resolved_at) else resolved_at
        resolved_display = resolved_at.strftime("%Y-%m-%d %H:%M")
    else:
        resolved_display = "an unknown date"

    resolution_text = issue.resolution or "Unspecified"
    metadata = {
        "source": "jira",
        "source_id": issue.issue_key,
        "source_display": issue.issue_key,
        "title": issue.summary,
        "summary": issue.summary,
        "status": issue.status,
        "resolution": issue.resolution,
        "resolution_date": issue.resolution_date.isoformat() if issue.resolution_date else None,
    }

    answer = (
        f"The most recently resolved Jira issue is {issue.issue_key}. "
        f"It is currently in status \"{issue.status}\" with resolution \"{resolution_text}\" "
        f"recorded on {resolved_display}."
    )

    safe_answer = _sanitize_answer(answer, [metadata])

    return {"answer": safe_answer, "sources": [metadata]}


def generate_answer(
    company_id: int,
    chatbot_id: int,
    query: str,
    top_k: int = 5,
    history: Optional[List[Dict[str, str]]] = None,
) -> dict:
    """Generate an answer using RAG with metadata-only context and safeguarded output."""

    if _is_latest_resolved_issue_query(query):
        return answer_latest_resolved_issue(company_id, chatbot_id)

    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in environment or settings.py")

    # 1. Retrieve context
    source_plan = _plan_retrieval_sources(query, history)
    pooled_documents: List[dict] = []
    retrieval_attempts: List[Dict[str, Any]] = []

    query_embedding = embed_text(query)

    for source_group in source_plan:
        group_documents = list(
            search_documents(
                company_id,
                chatbot_id,
                query,
                top_k,
                sources=source_group,
                query_embedding=query_embedding,
            )
        )
        pooled_documents = _merge_document_lists(pooled_documents, group_documents)
        retrieval_attempts.append(
            {
                "sources": list(source_group),
                "result_count": len(group_documents),
                "best_score": max(
                    (
                        float(doc.get("combined_score", 0.0))
                        for doc in group_documents
                    ),
                    default=0.0,
                ),
            }
        )

    fallback_documents = list(
        search_documents(
            company_id,
            chatbot_id,
            query,
            top_k,
            query_embedding=query_embedding,
        )
    )
    pooled_documents = _merge_document_lists(pooled_documents, fallback_documents)
    retrieval_attempts.append(
        {
            "sources": None,
            "result_count": len(fallback_documents),
            "best_score": max(
                (
                    float(doc.get("combined_score", 0.0))
                    for doc in fallback_documents
                ),
                default=0.0,
            ),
        }
    )

    documents = pooled_documents

    rewrite_threshold = float(
        getattr(
            settings,
            "RAG_QUERY_REWRITE_THRESHOLD",
            getattr(settings, "RAG_LOW_CONFIDENCE_THRESHOLD", _LOW_CONFIDENCE_THRESHOLD),
        )
    )
    preliminary_confidence = _compute_retrieval_confidence(documents)
    rewrite_details = None
    if preliminary_confidence < rewrite_threshold:
        expanded_documents, rewrite_details = _maybe_expand_with_query_rewrites(
            company_id,
            chatbot_id,
            query,
            top_k,
            documents,
        )
        documents = list(expanded_documents)

    documents = rerank_documents(query, documents)
    retrieval_confidence = _compute_retrieval_confidence(documents)
    threshold = float(getattr(settings, "RAG_LOW_CONFIDENCE_THRESHOLD", _LOW_CONFIDENCE_THRESHOLD))

    minimum_drafts = getattr(settings, "RAG_MIN_DRAFT_COUNT", 1)
    try:
        minimum_drafts = int(minimum_drafts)
    except (TypeError, ValueError):
        minimum_drafts = 1
    if minimum_drafts < 1:
        minimum_drafts = 1

    requested_drafts = minimum_drafts
    low_confidence_mode = False
    if retrieval_confidence < threshold:
        requested_drafts = getattr(
            settings,
            "RAG_LOW_CONFIDENCE_DRAFT_COUNT",
            _LOW_CONFIDENCE_DRAFT_COUNT,
        )
        try:
            requested_drafts = int(requested_drafts)
        except (TypeError, ValueError):
            requested_drafts = _LOW_CONFIDENCE_DRAFT_COUNT
        if requested_drafts < 2:
            requested_drafts = 2
        low_confidence_mode = True

    requested_drafts = max(minimum_drafts, requested_drafts)
    metadata_entries = [_metadata_from_document(doc) for doc in documents]
    research_notes = _summarize_metadata_entries(metadata_entries)

    # 2. Build context string that only contains safe metadata
    if research_notes:
        context_text = "\n".join(research_notes)
    else:
        context_text = "No supporting metadata was retrieved."

    # 3. Build prompt that emphasizes citations, safety, and recent history
    history_text = _format_history_for_prompt(history)
    history_section = (
        f"Recent conversation (most recent last):\n{history_text}\n\n" if history_text else ""
    )

    system_prompt = (
        "You are a helpful assistant that answers company-specific questions using only "
        "the structured metadata provided (e.g., Jira issues, Confluence pages, Git files). "
        "Each entry is supplied as metadata with a label like [jira:PROJ-123] along with optional titles "
        "and summaries. Always cite relevant sources using the exact [source:identifier] format. "
        "If the metadata is insufficient, say you do not know or ask for clarification. "
        "You may include short, sanitized code excerpts (a few lines at most) when they come directly "
        "from the supplied metadata and each excerpt is cited. Never expose secrets, credentials, or uncited "
        "source material. Use the recent conversation history, when available, to maintain context."
    )
    user_prompt = (
        f"{history_section}"
        "Research notes derived from the retrieved metadata sources:\n"
        f"{context_text}\n\n"
        f"Question: {query}\n\n"
        "Respond concisely, cite the sources using their [source:identifier] labels, and only include "
        "short, sanitized code excerpts when they are copied directly from a cited metadata snippet. "
        "Do not share secrets or credentials."
    )

    client = get_openai_client()

    completion_model = getattr(settings, "OPENAI_COMPLETION_MODEL", "gpt-4o-mini")
    if isinstance(completion_model, str):
        completion_model = completion_model.strip() or "gpt-4o-mini"
    else:
        completion_model = "gpt-4o-mini"

    completion_kwargs = {
        "model": completion_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1 if low_confidence_mode else 0.2,
    }
    if requested_drafts > 1:
        completion_kwargs["n"] = requested_drafts

    try:
        response = client.chat.completions.create(**completion_kwargs)
    except RateLimitError as exc:
        raise RuntimeError("OpenAI rate limit exceeded while generating an answer") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError("Failed to reach OpenAI while generating an answer") from exc

    choices = list(getattr(response, "choices", []) or [])
    if not choices:
        choices = [SimpleNamespace(message=SimpleNamespace(content=""))]

    drafts: List[Dict] = []
    for idx, choice in enumerate(choices):
        message = getattr(choice, "message", None)
        raw_text = getattr(message, "content", "") if message else ""
        evaluation = _evaluate_answer_draft(
            raw_text,
            metadata_entries,
            retrieval_confidence,
        )
        sanitized_text = _sanitize_answer(raw_text, metadata_entries)
        drafts.append(
            {
                "index": idx,
                "answer": sanitized_text,
                "raw_answer": raw_text,
                "score": evaluation["score"],
                "citations": evaluation["valid_citations"],
                "invalid_citations": evaluation["invalid_citations"],
                "found_citations": evaluation["found_citations"],
                "coverage": evaluation["coverage"],
                "contains_uncertainty": evaluation["contains_uncertainty"],
                "contains_refusal": evaluation["contains_refusal"],
            }
        )

    heuristic_index, _ = max(
        enumerate(drafts), key=lambda item: item[1]["score"]
    )

    selected_index = heuristic_index
    evaluation_method = "heuristic_citation_scoring"
    consensus_details: Optional[Dict[str, Any]] = None
    judge_details: Optional[Dict[str, Any]] = None
    judge_error: Optional[str] = None

    if len(drafts) > 1:
        consensus_details = _consensus_from_drafts(
            query,
            metadata_entries,
            drafts,
            judge_fn=lambda: _judge_answer_drafts(query, metadata_entries, drafts),
        )

        if consensus_details:
            consensus_index = consensus_details.get("index")
            method = consensus_details.get("method")
            if (
                isinstance(consensus_index, int)
                and 0 <= consensus_index < len(drafts)
                and method
            ):
                selected_index = consensus_index
                evaluation_method = method

            if consensus_details.get("judge"):
                judge_details = consensus_details["judge"]
            if consensus_details.get("judge_error"):
                judge_error = consensus_details["judge_error"]

        if judge_details and judge_details.get("rankings"):
            for entry in judge_details["rankings"]:
                idx = entry.get("index")
                if isinstance(idx, int) and 0 <= idx < len(drafts):
                    score = entry.get("score")
                    if isinstance(score, (int, float)):
                        drafts[idx]["judge_score"] = float(score)
                    feedback = entry.get("feedback")
                    if isinstance(feedback, str) and feedback:
                        drafts[idx]["judge_feedback"] = feedback

    best_draft = drafts[selected_index]

    citation_bonus = 0.1 * min(len(set(best_draft["citations"])), 3)
    uncertainty_penalty = 0.2 if (
        best_draft["contains_uncertainty"] or best_draft["contains_refusal"]
    ) else 0.0
    final_confidence = max(
        0.0,
        min(1.0, retrieval_confidence + citation_bonus - uncertainty_penalty),
    )

    reasoning_trace: Dict[str, Any] = {
        "retrieval_confidence": retrieval_confidence,
        "low_confidence_mode": low_confidence_mode,
        "requested_drafts": requested_drafts,
        "selected_draft_index": selected_index,
        "draft_scores": [draft["score"] for draft in drafts],
        "evaluation_method": evaluation_method,
    }
    if consensus_details:
        reasoning_trace["consensus"] = {
            key: value
            for key, value in consensus_details.items()
            if key not in {"judge", "judge_error"}
        }
    if judge_details:
        reasoning_trace["judge"] = judge_details
    if judge_error:
        reasoning_trace["judge_error"] = judge_error
    if evaluation_method != "llm_judge":
        reasoning_trace["heuristic_selected_index"] = heuristic_index

    reasoning_trace["retrieval_source_plan"] = [list(group) for group in source_plan]
    reasoning_trace["retrieval_source_attempts"] = retrieval_attempts
    reasoning_trace["research_notes"] = research_notes

    if rewrite_details:
        reasoning_trace["query_rewrite"] = rewrite_details

    return {
        "answer": best_draft["answer"],
        "sources": metadata_entries,
        "confidence": final_confidence,
        "retrieval_confidence": retrieval_confidence,
        "drafts": drafts,
        "reasoning_trace": reasoning_trace,
    }
_MAX_HISTORY_TURNS = 6
_MAX_HISTORY_CHARACTERS = 1600


def _format_history_for_prompt(
    history: Optional[List[Dict[str, str]]],
    max_turns: int = _MAX_HISTORY_TURNS,
    max_characters: int = _MAX_HISTORY_CHARACTERS,
) -> str:
    """Return a compact representation of ``history`` limited by turns and characters."""

    if not history:
        return ""

    sanitized_turns: List[Dict[str, str]] = []
    for turn in history[-max_turns:]:
        user_message = (turn.get("user") or "").strip()
        assistant_message = (turn.get("assistant") or "").strip()
        if not user_message and not assistant_message:
            continue
        sanitized_turns.append({"user": user_message, "assistant": assistant_message})

    if not sanitized_turns:
        return ""

    selected_blocks: List[str] = []
    consumed = 0

    for turn in reversed(sanitized_turns):
        segments: List[str] = []
        if turn["user"]:
            segments.append(f"User: {turn['user']}")
        if turn["assistant"]:
            segments.append(f"Assistant: {turn['assistant']}")

        if not segments:
            continue

        block = "\n".join(segments)
        separator = 2 if selected_blocks else 0
        projected = consumed + len(block) + separator

        if projected > max_characters:
            remaining = max_characters - consumed - separator
            if remaining <= 0:
                break

            local_remaining = remaining
            truncated_parts: List[str] = []
            for idx, segment in enumerate(segments):
                if idx > 0:
                    if local_remaining <= 1:
                        break
                    truncated_parts.append("\n")
                    local_remaining -= 1

                if local_remaining <= 0:
                    break

                truncated_segment = _truncate_text(segment, max(local_remaining, 16))
                if not truncated_segment:
                    break

                # Ensure we only account for the actual characters we will append
                available = min(len(truncated_segment), local_remaining)
                truncated_parts.append(truncated_segment[:available])
                local_remaining -= available
                if local_remaining <= 0:
                    break

            truncated_block = "".join(truncated_parts).rstrip()
            if truncated_block:
                selected_blocks.append(truncated_block if truncated_block.endswith("…") else truncated_block + "…")
            break

        selected_blocks.append(block)
        consumed = projected

    if not selected_blocks:
        return ""

    selected_blocks.reverse()
    return "\n\n".join(selected_blocks)
