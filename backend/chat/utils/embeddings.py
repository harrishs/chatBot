import logging
import time

from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from django.conf import settings
from chat.models import Document
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db import connection
from pgvector.django import CosineDistance
from math import sqrt


logger = logging.getLogger(__name__)

_shared_openai_client = None


def get_openai_client() -> OpenAI:
    """Return a shared OpenAI client instance configured from settings."""
    global _shared_openai_client

    if _shared_openai_client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in environment or settings.py")

        _shared_openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

    return _shared_openai_client

def embed_text(text: str) -> list:
    """
    Generate a vector embedding for a given text using OpenAI.
    Returns a list of floats (embedding vector).
    """
    client = get_openai_client()

    max_attempts = 6
    base_backoff_seconds = 1
    max_backoff_seconds = 10

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return response.data[0].embedding
        except RateLimitError as exc:
            if attempt < max_attempts:
                sleep_seconds = min(
                    base_backoff_seconds * (2 ** (attempt - 1)),
                    max_backoff_seconds,
                )
                logger.warning(
                    "OpenAI rate limit encountered while generating embeddings (attempt %d/%d). "
                    "Retrying after %d seconds.",
                    attempt,
                    max_attempts,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue

            final_message = getattr(exc, "message", str(exc))
            logger.error(
                "OpenAI rate limit persisted after %d attempts while generating embeddings: %s",
                max_attempts,
                final_message,
            )
            raise RuntimeError(
                "OpenAI embeddings sync failed after repeated rate limit errors; aborting job."
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise RuntimeError("Failed to reach OpenAI while generating embeddings") from exc

def chunk_text(text, max_tokens=1000):
    max_chars = max_tokens * 4

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end
    return chunks


def _normalize_source_id(source_id: str) -> str:
    if not source_id:
        return source_id
    return source_id.split("_part_", 1)[0]


def save_document(company, chatbot, source, source_id, content):
    """
    Save a document with its embedding to the database.
    """
    chunks = chunk_text(content, max_tokens=1000)

    docs = []
    for idx, chunk in enumerate(chunks):
        embedding = embed_text(chunk)
        chunk_id = f"{source_id}_part_{idx}" if len(chunks) > 1 else source_id
        doc, _ = Document.objects.update_or_create(
            company=company,
            chatbot=chatbot,
            source=source,
            source_id=chunk_id,
            defaults={"content": chunk, "embedding": embedding},
        )
        docs.append(doc)
    return docs

def search_documents(company_id, chatbot_id, query, top_k=5):
    """
    Semantic search: find the most relevant documents to a query.
    Uses cosine similarity with pgvector.
    """
    # 1. Embed the query text
    query_embedding = embed_text(query)

    # Ensure a positive slice window to avoid negative indices when slicing querysets
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 1
    if top_k < 1:
        top_k = 1

    # 2. Run similarity search using pgvector helpers
    base_queryset = Document.objects.filter(company_id=company_id, chatbot_id=chatbot_id)

    if connection.vendor == 'sqlite':
        def cosine_similarity(vec1, vec2):
            dot = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = sqrt(sum(a * a for a in vec1))
            norm2 = sqrt(sum(b * b for b in vec2))
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)

        scored_docs = [
            (doc, cosine_similarity(doc.embedding, query_embedding))
            for doc in base_queryset
        ]
        scored_docs.sort(key=lambda item: item[1], reverse=True)
        rows = [doc for doc, _ in scored_docs[:top_k]]
        scores = {doc.id: score for doc, score in scored_docs}

        return [
            {
                "id": doc.id,
                "source": doc.source,
                "source_id": doc.source_id,
                "source_display": _normalize_source_id(doc.source_id),
                "source_url": _normalize_source_id(doc.source_id)
                if _normalize_source_id(doc.source_id).startswith("http")
                else None,
                "content": doc.content,
                "similarity": float(scores.get(doc.id)),
            }
            for doc in rows
        ]

    queryset = (
        base_queryset
        .annotate(distance=CosineDistance("embedding", query_embedding))
        .annotate(
            similarity=ExpressionWrapper(
                Value(1.0) - F("distance"),
                output_field=FloatField(),
            )
        )
        .order_by("distance")
    )

    rows = queryset[:top_k]

    return [
        {
            "id": doc.id,
            "source": doc.source,
            "source_id": doc.source_id,
            "source_display": _normalize_source_id(doc.source_id),
            "source_url": _normalize_source_id(doc.source_id)
            if _normalize_source_id(doc.source_id).startswith("http")
            else None,
            "content": doc.content,
            "similarity": float(doc.similarity) if doc.similarity is not None else None,
        }
        for doc in rows
    ]
