"""Retrieval helpers: similarity search + rerank-ready query."""
from config import get_store


def retrieve(query: str, k: int = 4):
    store = get_store()
    return store.similarity_search_with_score(query, k=k)
