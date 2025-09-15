import openai
from django.conf import settings
from chat.models import Document
from django.db import connection

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

def save_document(company, source, source_id, content):
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
            source=source,
            source_id=chunk_id,
            defaults={"content": chunk, "embedding": embedding},
        )
        docs.append(doc)
    return docs

def search_documents(company_id, query, top_k=5):
    """
    Semantic search: find the most relevant documents to a query.
    Uses cosine similarity with pgvector.
    """
    # 1. Embed the query text
    query_embedding = embed_text(query)

    # 2. Run similarity search
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, source, source_id, content,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM chat_document
            WHERE company_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, [query_embedding, company_id, query_embedding, top_k])

        rows = cursor.fetchall()

    # 3. Return structured results
    return [
        {
            "id": row[0],
            "source": row[1],       # "jira", "confluence", or "github"
            "source_id": row[2],    # ticket id, page id, file path
            "content": row[3],
            "similarity": float(row[4]),
        }
        for row in rows
    ]