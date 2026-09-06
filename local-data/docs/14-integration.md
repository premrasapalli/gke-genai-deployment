# How All the Services Integrate

The platform is not one program — it is several **microservices** that cooperate
over the network. This file explains who talks to whom, how they discover each
other, and exactly what happens on a `/chat` call and on a `/rag` call.

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

## What happens on `POST /chat`

1. Client sends `{"messages": [...]}` to the **gateway**.
2. The gateway looks at `LLM_URL` (default `http://serving-llm:8000/v1`) and
   forwards the request to the **serving-llm** service.
3. The LLM generates a reply and returns it to the gateway.
4. The gateway returns the reply to the client.

There is no retrieval here — it is a plain conversation with the model.

## What happens on `POST /rag`

This is where all the services cooperate:

1. Client sends `{"query": "..."}` to the **gateway**.
2. The gateway validates and forwards to the **rag-service** (`RAG_URL`).
3. The rag-service runs the answer chain (`rag/chain.py`):
   a. **Embed the query** — it calls `serving-embedding` (TEI) to turn the
      question into a vector.
   b. **Search the store** — it searches the Chroma vector database (on the
      `rag-data` volume) for the top-4 closest chunks.
   c. **Build a grounded prompt** — it inserts those chunks as context.
   d. **Ask the LLM** — it sends the prompt to `serving-llm` (Ollama) for the
      final grounded answer.
4. The rag-service returns the answer to the gateway, which returns it to the
   client.

```
Client -> gateway -> rag-service -> serving-embedding (embed query)
                              |          -> Chroma (retrieve chunks)
                              |          -> serving-llm (generate grounded answer)
                              v
                         answer to client
```

## Integration during ingestion

The `rag-ingest` job also uses `serving-embedding` (to embed each chunk) and
writes to the same Chroma store (`rag-data` volume) that the rag-service reads.
This is why the store must support read-write-many: two different processes
(ingest writing, service reading) share it.

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
