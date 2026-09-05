"""Shared RAG configuration and vector store factory.

Uses an OpenAI-compatible embedding endpoint (works with vLLM or Ollama).
"""
import os

from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

COLLECTION = os.environ.get("RAG_COLLECTION", "knowledge_base")
PERSIST_DIR = os.environ.get("RAG_PERSIST_DIR", "/data/chroma")

# OpenAI-compatible embedding endpoint (vLLM or Ollama)
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL", "http://serving-embedding:8001/v1"
)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_KEY = os.environ.get("EMBEDDING_API_KEY", "EMPTY")


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=EMBEDDING_KEY,
        base_url=EMBEDDING_BASE_URL,
    )


def get_store(collection: str = COLLECTION) -> Chroma:
    return Chroma(
        collection_name=collection,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
        client_settings=Settings(anonymized_telemetry=False),
    )
