# Integration — End-to-End: How Services Talk to Each Other (and why)

Microservices only work if their connections, message shapes, and contracts are
explicit. This file traces a request from the outside world through every hop,
and answers **why each hop exists**.

## The network topology (ClusterIP DNS names)

| Service            | DNS name                          | Port | Serves                     |
|--------------------|-----------------------------------|------|----------------------------|
| gateway            | `gateway` / via LB 34.63.204.167  | 80   | the public entry point     |
| rag-service        | `rag-service`                     | 8080 | retrieval + RAG chain      |
| serving-embedding  | `serving-embedding`               | 8001 | text embeddings (TEI)      |
| serving-llm        | `serving-llm`                     | 8000 | chat completions (Ollama)  |

Kubernetes Services give each workload a stable DNS name **and** load-balance
across its pods. Why that matters: pods come and go, but `serving-llm` never
changes, so the gateway config never changes.

## Hop-by-hop, /chat (plain conversation)

```
Client ──► gateway (/chat)
              │ POST {messages:[...]}  with model = LLM_MODEL
              ▼
          serving-llm (/v1/chat/completions, OpenAI-compatible)
              │ stream-generation of tokens
              ▼
          gateway returns {answer} ──► client
```
**Why each hop:**
- gateway → LLM: the LLM needs an OpenAI-compatible body (`model`,
  `messages`, `temperature`). The gateway translates the user's simple payload.
- The response shape (`choices[0].message.content`) is OpenAI-standard, so
  swapping vLLM↔Ollama never touches the gateway code.

## Hop-by-hop, /rag (grounded answer)

```
Client ──► gateway (/rag)
              │ POST {query, k:4}
              ▼
          rag-service (/answer)
              │ 1) embed the query via serving-embedding (bge-small-en-v1.5)
              │ 2) similarity-search Chroma (knowledge_base) for k chunks
              │ 3) build a grounded prompt from the chunks
              │ 4) call serving-llm to generate the answer from THAT context
              ▼
          gateway returns {answer} ──► client
```

**Why the room-service choreography:**

| Step | Why each hop exists                              |
|------|--------------------------------------------------|
| query → embedding | the query must be in the same vector space as the docs, using the SAME model used at ingest (bge-small-en-v1.5). Mismatch ⇒ nonsense retrieval |
| embed → Chroma | the vector index (on the shared `rag-data` volume) is the docs' semantic memory |
| chunks → LLM prompt | grounded prompt: "answer only from Context", then chunk text — reduces hallucination by constraining the model |
| LLM → answer | the transformers model turns retrieved facts into a natural-language answer |

## Hop-by-hop, ingestion (offline path)

```
GCS bucket ──► cronjob seed-docs (gsutil rsync) ──► /data/docs (rag-data PVC)
                                                     │
rag-ingest (python -m ingest --dir /data/docs):      ▼
    chunk every .md/.txt ──► embed via TEI ──► upsert into /data/chroma
```

**Why this shape:** two different processes (the always-on rag-service reading
and the batch ingest writing) touch the same volume — the reason `rag-data` is
RWX (NFS) rather than RWO. Only a read-write-many volume allows "writer pod +
reader pod at the same time".

## Consistency rules that keep the wiring alive

1. **Embedding model identical** at ingest and query (env `EMBEDDING_MODEL`,
   default `BAAI/bge-small-en-v1.5`).
2. **LLM model name matches what the server serves:** Ollama exposes
   `qwen2.5:0.5b`; vLLM would expose `genai-model`. Set `LLM_MODEL` in gateway
   AND rag-service to the same string or you get 404 from the LLM.
3. **URL defaults match service names** (`LLM_URL`, `RAG_URL`,
   `EMBEDDING_BASE_URL`, `EMBED_URL`) — all of these are plain env vars in the
   manifests, so keeping integration working is a config discipline, not a code
   change.

## Failure signatures of mis-wiring
- `/rag` answers generically with zero docs found ⇒ either the store isn't
  populated, or embedding model mismatch.
- `404 model not found` from `/chat` ⇒ `LLM_MODEL` doesn't match what the
  serving backend exposes.
- `ImagePullBackOff` on EVERY pod ⇒ the overlay (registry rewrite) wasn't
  applied — pods requested `docker.io/genai/...`.