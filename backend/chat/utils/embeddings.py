import logging
import time
from math import sqrt
from typing import Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import Coalesce
from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from pgvector.django import CosineDistance

from chat.models import Document


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

def search_documents(
    company_id: int,
    chatbot_id: int,
    query: str,
    top_k: int = 5,
    sources: Optional[Iterable[str]] = None,
):
    """Search for relevant documents using vector and lexical signals."""

    query_embedding = embed_text(query)
    query_tokens = _tokenize_query(query)

    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 1
    if top_k < 1:
        top_k = 1

    vector_weight = getattr(settings, "RAG_VECTOR_WEIGHT", 0.7)
    lexical_weight = getattr(settings, "RAG_LEXICAL_WEIGHT", 0.3)
    total_weight = vector_weight + lexical_weight
    if total_weight <= 0:
        vector_weight = 1.0
        lexical_weight = 0.0
    else:
        vector_weight /= total_weight
        lexical_weight /= total_weight

    base_queryset = Document.objects.filter(company_id=company_id, chatbot_id=chatbot_id)
    if sources:
        base_queryset = base_queryset.filter(source__in=list(sources))

    if connection.vendor == 'sqlite':
        scored_docs = []
        for doc in base_queryset:
            similarity = _cosine_similarity(doc.embedding, query_embedding)
            lexical_raw = 0.0
            if query_tokens:
                lowered = (doc.content or "").lower()
                lexical_raw = sum(lowered.count(token) for token in query_tokens)

            scored_docs.append((doc, similarity, lexical_raw))

        max_lexical = max((item[2] for item in scored_docs), default=0.0)

        enriched = []
        for doc, similarity, lexical_raw in scored_docs:
            lexical_score = (lexical_raw / max_lexical) if max_lexical > 0 else 0.0
            combined_score = (vector_weight * similarity) + (lexical_weight * lexical_score)
            enriched.append(
                {
                    "doc": doc,
                    "similarity": similarity,
                    "lexical_score": lexical_score,
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

        return [
            {
                "id": item["doc"].id,
                "source": item["doc"].source,
                "source_id": item["doc"].source_id,
                "source_display": _normalize_source_id(item["doc"].source_id),
                "source_url": _normalize_source_id(item["doc"].source_id)
                if _normalize_source_id(item["doc"].source_id).startswith("http")
                else None,
                "content": item["doc"].content,
                "similarity": float(item["similarity"]),
                "lexical_score": float(item["lexical_score"]),
                "combined_score": float(item["combined_score"]),
            }
            for item in rows
        ]

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
        search_query = SearchQuery(query, config="english")
        queryset = queryset.annotate(
            lexical_rank=SearchRank(search_vector, search_query)
        )
    else:
        queryset = queryset.annotate(
            lexical_rank=Value(0.0, output_field=FloatField())
        )

    queryset = queryset.annotate(
        lexical_score=ExpressionWrapper(
            Coalesce(F("lexical_rank"), Value(0.0)),
            output_field=FloatField(),
        )
    )

    queryset = queryset.annotate(
        combined_score=ExpressionWrapper(
            Value(vector_weight) * Coalesce(F("similarity"), Value(0.0))
            + Value(lexical_weight) * F("lexical_score"),
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
            "lexical_score": float(doc.lexical_score) if doc.lexical_score is not None else 0.0,
            "combined_score": float(doc.combined_score) if doc.combined_score is not None else 0.0,
        }
        for doc in rows
    ]


def rerank_documents(query: str, documents: Sequence[dict]) -> List[dict]:
    """Re-rank documents using a higher-fidelity embedding model when available."""

    if not documents:
        return []

    rerank_model = getattr(settings, "OPENAI_RERANK_EMBEDDING_MODEL", "").strip()
    if not rerank_model:
        return list(documents)

    try:
        query_embedding = embed_text(query, model=rerank_model)
    except Exception:  # pragma: no cover - defensive fallback
        logger.exception(
            "Falling back to original document ordering after failing to embed query for reranking"
        )
        return list(documents)

    scored: List[Tuple[dict, Optional[float]]] = []
    for doc in documents:
        content = (doc.get("content") or "").strip()
        if not content:
            scored.append((doc, None))
            continue

        try:
            doc_embedding = embed_text(content, model=rerank_model)
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception(
                "Failed to embed document %s for reranking; retaining original order",
                doc.get("id"),
            )
            scored.append((doc, None))
            continue

        score = _cosine_similarity(query_embedding, doc_embedding)
        scored.append((doc, score))

    scored.sort(
        key=lambda item: (
            item[1] is None,
            -(item[1] if item[1] is not None else 0.0),
            item[0].get("id"),
        )
    )

    reranked: List[dict] = []
    for doc, score in scored:
        updated = dict(doc)
        if score is not None:
            updated["rerank_score"] = float(score)
        else:
            updated["rerank_score"] = None
        reranked.append(updated)

    return reranked
