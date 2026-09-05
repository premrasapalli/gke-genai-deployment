import json
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config

router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    max_tokens: int = 256
    temperature: float = 0.2


class RagRequest(BaseModel):
    query: str
    k: int = 4


class Reply(BaseModel):
    answer: str


def _openai_payload(messages, max_tokens, temperature):
    return {
        "model": config.LLM_MODEL,
        "messages": [m.dict() for m in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.post("/chat", response_model=Reply)
async def chat(req: ChatRequest):
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{config.LLM_URL}/chat/completions",
            json=_openai_payload(req.messages, req.max_tokens, req.temperature),
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return Reply(answer=r.json()["choices"][0]["message"]["content"])


@router.post("/rag", response_model=Reply)
async def rag(req: RagRequest):
    # The rag-service exposes a /answer endpoint that does retrieval + generation.
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{config.RAG_URL}/answer", json={"query": req.query, "k": req.k}
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return Reply(answer=r.json()["answer"])


@router.get("/models")
async def models():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{config.LLM_URL}/models")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()
