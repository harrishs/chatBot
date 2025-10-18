import re
from collections import Counter
from typing import Dict, List, Optional

from django.utils import timezone

from openai import APIConnectionError, APITimeoutError, RateLimitError
from django.conf import settings
from chat.utils.embeddings import get_openai_client, search_documents
from chat.models import JiraIssue


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


def _metadata_from_document(document: Dict) -> Dict:
    """Convert a search document into safe metadata for prompts and responses."""

    content = (document.get("content") or "").strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    title = lines[0][:120] if lines else ""

    summary_lines: List[str] = []
    if lines:
        summary_lines.extend(lines[:8])

        important_prefixes = ("Resolved at", "Completion summary")
        for line in lines[8:]:
            if line.startswith(important_prefixes) and line not in summary_lines:
                summary_lines.append(line)

    summary_source = " ".join(summary_lines) if summary_lines else ""
    summary = _truncate_text(summary_source, 320)

    metadata = {
        key: document.get(key)
        for key in (
            "id",
            "source",
            "source_id",
            "source_display",
            "source_url",
            "similarity",
        )
        if document.get(key) is not None
    }
    if title:
        metadata["title"] = title
    if summary:
        metadata["summary"] = summary

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


def _sanitize_answer(answer: str, metadata_list: List[Dict]) -> str:
    """Remove code blocks and ensure traceable citations are present."""

    sanitized = answer or ""
    sanitized = re.sub(r"```.*?```", "[omitted code block]", sanitized, flags=re.DOTALL)

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
