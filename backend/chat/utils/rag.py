import re
from collections import Counter
from typing import Dict, List, Optional

from django.utils import timezone

from openai import APIConnectionError, APITimeoutError, RateLimitError
from django.conf import settings
from chat.utils.embeddings import get_openai_client, rerank_documents, search_documents
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

_MAX_METADATA_SNIPPET_CHARACTERS = 1200


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

    raw_chunk_text = stored_metadata.get("chunk_text") or (document.get("content") or "")
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

    source_url = stored_metadata.get("source_url") or document.get("source_url")
    if source_url:
        metadata["source_url"] = source_url

    if title:
        metadata["title"] = title
    if summary:
        metadata["summary"] = summary
    if excerpt:
        metadata["excerpt"] = excerpt
    if snippet:
        metadata["snippet"] = snippet

    for key in (
        "path",
        "space_key",
        "section_heading",
        "chunk_index",
        "chunk_count",
        "chunk_tokens",
        "chunk_char_count",
    ):
        value = stored_metadata.get(key)
        if value not in (None, ""):
            metadata[key] = value

    keyword_source = summary or summary_source
    keywords = _extract_keywords(keyword_source) if keyword_source else []
    if keywords:
        metadata["keywords"] = ", ".join(keywords)

    return metadata


def _format_metadata_for_prompt(metadata: Dict) -> str:
    """Format metadata for inclusion in the LLM prompt."""

    label_identifier = metadata.get("source_display") or metadata.get("source_id") or "unknown"
    label_source = metadata.get("source") or "source"
    sections = [f"[{label_source}:{label_identifier}]"]

    title = metadata.get("title")
    if title:
        sections.append(f"Title: {title}")

    section_heading = metadata.get("section_heading")
    if section_heading and section_heading != title:
        sections.append(f"Section: {section_heading}")

    path = metadata.get("path")
    if path:
        sections.append(f"Path: {path}")

    space_key = metadata.get("space_key")
    if space_key:
        sections.append(f"Space: {space_key}")

    chunk_index = metadata.get("chunk_index")
    chunk_count = metadata.get("chunk_count")
    if isinstance(chunk_index, int) and isinstance(chunk_count, int):
        sections.append(f"Chunk: {chunk_index + 1} of {chunk_count}")
    elif isinstance(chunk_index, int):
        sections.append(f"Chunk index: {chunk_index}")

    summary = metadata.get("summary")
    if summary and summary != title:
        sections.append(f"Summary: {summary}")

    source_url = metadata.get("source_url")
    if source_url:
        sections.append(f"URL: {source_url}")

    similarity = metadata.get("similarity")
    if isinstance(similarity, float):
        sections.append(f"Similarity: {similarity:.3f}")

    keywords = metadata.get("keywords")
    if keywords:
        sections.append(f"Keywords: {keywords}")

    snippet = metadata.get("snippet") or metadata.get("excerpt")
    if snippet:
        sections.append("")
        sections.append("Snippet:")
        sections.append(snippet)

    return "\n".join(sections)


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


def _redact_sensitive_tokens(value: str) -> str:
    """Redact known sensitive token patterns within ``value``."""

    value = _SECRET_KEY_VALUE_PATTERN.sub(_redacted_secret_value, value)
    value = _OPENAI_KEY_PATTERN.sub("[redacted sensitive data]", value)
    value = _PEM_BLOCK_PATTERN.sub("[redacted sensitive data]", value)
    return value


def _sanitize_answer(answer: str, metadata_list: List[Dict]) -> str:
    """Remove unsafe snippets while preserving legitimate technical explanations."""

    sanitized = answer or ""

    def _sanitize_code_block(match: re.Match) -> str:
        language = match.group("lang") or ""
        newline = match.group("newline") or ""
        content = match.group("content") or ""
        cleaned_content = _redact_sensitive_tokens(content)
        return f"```{language}{newline}{cleaned_content}```"

    parts: List[str] = []
    last_end = 0
    has_blocks = False
    for block in _CODE_BLOCK_PATTERN.finditer(sanitized):
        has_blocks = True
        prefix = sanitized[last_end : block.start()]
        if prefix:
            parts.append(_redact_sensitive_tokens(prefix))
        parts.append(_sanitize_code_block(block))
        last_end = block.end()

    remainder = sanitized[last_end:]
    if has_blocks:
        if remainder:
            parts.append(_redact_sensitive_tokens(remainder))
        sanitized = "".join(parts)
    else:
        sanitized = _redact_sensitive_tokens(sanitized)

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
    documents = search_documents(company_id, chatbot_id, query, top_k)
    documents = rerank_documents(query, documents)
    metadata_entries = [_metadata_from_document(doc) for doc in documents]

    # 2. Build context string that only contains safe metadata
    if metadata_entries:
        context_sections = [_format_metadata_for_prompt(metadata) for metadata in metadata_entries]
        context_text = "\n\n".join(context_sections)
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
        "Explicitly refuse to output code snippets, secrets, or credentials, and explain that you can only "
        "discuss the metadata at a high level. Use the recent conversation history, when available, to maintain context."
    )
    user_prompt = (
        f"{history_section}"
        "Metadata entries:\n"
        f"{context_text}\n\n"
        f"Question: {query}\n\n"
        "Respond concisely, cite the sources using their [source:identifier] labels, and do not reveal code or secrets."
    )

    client = get_openai_client()

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except RateLimitError as exc:
        raise RuntimeError("OpenAI rate limit exceeded while generating an answer") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError("Failed to reach OpenAI while generating an answer") from exc

    raw_answer = response.choices[0].message.content or ""
    safe_answer = _sanitize_answer(raw_answer, metadata_entries)

    return {"answer": safe_answer, "sources": metadata_entries}
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
