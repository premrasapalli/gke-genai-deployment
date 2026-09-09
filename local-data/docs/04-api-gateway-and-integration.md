# API Gateway & Service Integration

This file covers the API gateway (the single entry point) and how all services
integrate: who talks to whom, how they discover each other, and hop-by-hop
request traces.

---

# The API Gateway

The **API gateway** is a FastAPI application (a Python web framework) that is
the single entry point into the whole AI system. It lives in the `gateway/`
directory and runs as the `gateway` Kubernetes deployment.

## Why have a gateway at all?

The internals — the LLM server, the embedding server, the RAG service — each
have their own addresses and details. A frontend or a CLI should not need to
know about any of them. The gateway gives clients:

- **One stable URL and port** (port 80 via the `gateway` Service).
- **Simple, stable endpoints.**
- **Optional API-key authentication.**

It also hides which model server is installed underneath (Ollama vs vLLM).

## The endpoints

- `POST /chat` — a plain chat with the LLM. You send messages; it streams/returns
  the model's reply.
- `POST /rag` — ask a question grounded in your documents. The gateway forwards
  to the rag service, which does retrieval and generation.
- `GET /models` — lists the models the serving backend currently has loaded.
- `GET /healthz` — readiness/health check used by Kubernetes probes.

## How the gateway talks to everything

The gateway is configured entirely with environment variables:

- `LLM_URL` — where the LLM lives (defaults to `http://serving-llm:8000/v1`).
- `LLM_MODEL` — the served model name (e.g. `qwen2.5:0.5b` or `genai-model`).
- `RAG_URL` — the rag service (defaults to `http://rag-service:8080`).
- `API_KEY` — optional shared secret for `X-API-Key` header auth.

Because these are just values in the Kubernetes manifest, pointing the whole
system at a different model or backend is a config change, not a code change.

---

# How All the Services Integrate

The platform is not one program — it is several **microservices** that cooperate
over the network.

## The cast of services

| Service | What it does | Port |
|---------|--------------|------|
| gateway | Public entry point, FastAPI routers | 80 |
| serving-llm | The LLM (Ollama in CPU mode, vLLM in GPU mode) | 8000 |
| serving-embedding | TEI embeddings | 8001 |
| rag-service | Retrieval + grounded answer | 8080 |
| rag-ingest | CronJob that indexes documents | (job) |

## How they find each other

Kubernetes gives every service a stable **DNS name** that equals the service
name. Inside the cluster, `http://serving-llm:8000` reaches the LLM, and
`http://rag-service:8080` reaches the RAG service. The manifests wire these up
through **environment variables**, so reconfiguring where something points is a
single, visible config change.

## Integration point: OpenAI-compatible APIs

The clever design choice is that the LLM (Ollama or vLLM) and the embedding
server (TEI) both expose **OpenAI-compatible** endpoints. That means:

- The gateway and the RAG chain use the standard OpenAI Python client.
- The same client code works whether the backend is vLLM (GPU) or Ollama (CPU).
- The only thing that changes is the base URL and the model name — never the
  calling code.

---

# End-to-End Integration Flow

## Network topology (ClusterIP DNS names)

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
- gateway -> LLM: the LLM needs an OpenAI-compatible body (`model`,
  `messages`, `temperature`). The gateway translates the user's simple payload.
- The response shape (`choices[0].message.content`) is OpenAI-standard, so
  swapping vLLM<->Ollama never touches the gateway code.

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

| Step | Why each hop exists                              |
|------|--------------------------------------------------|
| query -> embedding | the query must be in the same vector space as the docs, using the SAME model used at ingest (bge-small-en-v1.5). Mismatch = nonsense retrieval |
| embed -> Chroma | the vector index (on the shared `rag-data` volume) is the docs' semantic memory |
| chunks -> LLM prompt | grounded prompt: "answer only from Context", then chunk text — reduces hallucination by constraining the model |
| LLM -> answer | the transformers model turns retrieved facts into a natural-language answer |

## Hop-by-hop, ingestion (offline path)

```
GCS bucket ──► cronjob seed-docs (gsutil rsync) ──► /data/docs (rag-data PVC)
                                                     │
rag-ingest (python -m ingest --dir /data/docs):      ▼
    chunk every .md/.txt ──► embed via TEI ──► upsert into /data/chroma
```

**Why this shape:** two different processes (the always-on rag-service reading
and the batch ingest writing) touch the same volume — the reason `rag-data` is
RWX (NFS) rather than RWO.

## Keeping integrations consistent

Three things must always line up:

1. **Embedding model** — same value (`BAAI/bge-small-en-v1.5`) at ingest and
   query time, or retrieval breaks.
2. **LLM model name** — the gateway and rag-service `LLM_MODEL` must equal what
   the serving backend exposes (`qwen2.5:0.5b` for Ollama, `genai-model` for
   vLLM).
3. **URLs** — each service's endpoint variables must point at the correct
   Kubernetes service names.

Because these are all plain environment variables in the manifests, keeping the
integration working is mostly a matter of keeping these settings in sync.

## Failure signatures of mis-wiring

- `/rag` answers generically with zero docs found => either the store isn't
  populated, or embedding model mismatch.
- `404 model not found` from `/chat` => `LLM_MODEL` doesn't match what the
  serving backend exposes.
- `ImagePullBackOff` on EVERY pod => the overlay (registry rewrite) wasn't
  applied — pods requested `docker.io/genai/...`.
