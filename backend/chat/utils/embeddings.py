import openai
from django.conf import settings
from chat.models import Document
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db import connection
from pgvector.django import CosineDistance
from math import sqrt

def embed_text(text: str) -> list:
    """
    Generate a vector embedding for a given text using OpenAI.
    Returns a list of floats (embedding vector).
    """
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in environment or settings.py")

    openai.api_key = settings.OPENAI_API_KEY

    response = openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def chunk_text(text, max_tokens=1000):
    max_chars = max_tokens * 4

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end
    return chunks

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
            "content": doc.content,
            "similarity": float(doc.similarity) if doc.similarity is not None else None,
        }
        for doc in rows
    ]
