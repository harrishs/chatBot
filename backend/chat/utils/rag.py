from openai import APIConnectionError, APITimeoutError, RateLimitError
from django.conf import settings
from chat.utils.embeddings import get_openai_client, search_documents


def generate_answer(company_id: int, chatbot_id: int, query: str, top_k: int = 5) -> dict:
    """
    Generate an answer using RAG:
    - Search documents for context
    - Build a prompt with query + docs
    - Ask OpenAI LLM for an answer
    """
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in environment or settings.py")

    # 1. Retrieve context
    docs = search_documents(company_id, chatbot_id, query, top_k)

    # 2. Build context string
    context_text = "\n\n".join([f"[{d['source']}:{d['source_id']}]\n{d['content']}" for d in docs])

    # 3. Build prompt
    system_prompt = (
        "You are a helpful assistant that answers questions "
        "using only the provided company documents (Jira, Confluence, GitHub). "
        "Always cite the source IDs (e.g., [jira:PROJ-123], [confluence:456]) in your answer. "
        "Do not make any assumptions. If the context does not contain enough information, "
        "ask the user for clarification or say you do not know. "
        "Never make up information or hallucinate answers."
    )
    user_prompt = f"Context:\n{context_text}\n\nQuestion: {query}"

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

    answer = response.choices[0].message.content
    return {"answer": answer, "sources": docs}
