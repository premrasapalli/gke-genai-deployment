import os

LLM_URL = os.environ.get("LLM_URL", "http://serving-llm:8000/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
RAG_URL = os.environ.get("RAG_URL", "http://rag-service:8080")
EMBED_URL = os.environ.get("EMBED_URL", "http://serving-embedding:8001/v1")
