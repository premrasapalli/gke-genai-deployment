"""RAG answer chain: retrieve context, then ask the LLM with the context."""
from openai import OpenAI

from config import EMBEDDING_MODEL
from retriever import retrieve

LLM_BASE_URL = "http://serving-llm:8000/v1"
LLM_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def _build_context(query: str, k: int = 4) -> str:
    hits = retrieve(query, k=k)
    parts = []
    for i, (doc, score) in enumerate(hits, 1):
        parts.append(
            f"[{i}] (score={score:.3f})\n{doc.page_content.strip()}"
        )
    return "\n\n".join(parts)


def rag_answer(query: str, k: int = 4) -> str:
    client = OpenAI(base_url=LLM_BASE_URL, api_key="EMPTY")
    context = _build_context(query, k)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise assistant. Answer ONLY from the provided "
                "context. If the context does not contain the answer, say you "
                "don't know. Cite the context section number."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {query}",
        },
    ]
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=512,
        temperature=0.1,
    )
    return resp.choices[0].message.content
