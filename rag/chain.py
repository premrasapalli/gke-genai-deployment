"""RAG answer chain: retrieve context, then ask the LLM with the context."""
import os

from openai import OpenAI

from config import EMBEDDING_MODEL
from retriever import retrieve

# vLLM is served with --served-model-name genai-model (see k8s serving-llm.yaml),
# so the model name used by the RAG chain MUST match it or /v1 returns a 404.
# Override via env when the served name differs (e.g. docker-compose).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://serving-llm:8000/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "genai-model")


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
