import json
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import config

router = APIRouter()


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    # Auth is opt-in: only enforced when config.API_KEY is set.
    if not config.API_KEY:
        return None
    # Constant-time-ish compare to avoid leaking the key length via timing.
    import hmac

    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return None


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


@router.post("/chat", response_model=Reply, dependencies=[Depends(require_api_key)])
async def chat(req: ChatRequest):
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{config.LLM_URL}/chat/completions",
            json=_openai_payload(req.messages, req.max_tokens, req.temperature),
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return Reply(answer=r.json()["choices"][0]["message"]["content"])


@router.post("/rag", response_model=Reply, dependencies=[Depends(require_api_key)])
async def rag(req: RagRequest):
    # The rag-service exposes a /answer endpoint that does retrieval + generation.
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{config.RAG_URL}/answer", json={"query": req.query, "k": req.k}
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return Reply(answer=r.json()["answer"])


@router.get("/models", dependencies=[Depends(require_api_key)])
async def models():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{config.LLM_URL}/models")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()
