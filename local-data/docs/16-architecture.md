# Architecture — and Why Each Layer Exists

This document maps the whole platform and explains, for every layer you add,
**why you add it**. Architecture is not about drawing boxes — every box exists
because it solves a specific problem. Read this before changing anything.

## The layers, and the WHY of each

```
CLIENTS (browser / curl)                     WHY: users need a way in; they should
   │                                             not know about cluster internals
   ▼
API GATEWAY (FastAPI, :80)                   WHY: a single door that hides the
   │                                             messy internals behind simple,
   │                                             stable endpoints (/chat, /rag)
   ▼
RAG SERVICE (:8080)                          WHY: retrieval is a separate concern
   │                                             (own scaling, own logic), so it
   │                                             does not entangle the gateway
   ▼
EMBEDDING TEI (:8001)   ──►  LLM (Ollama/vLLM :8000)
                                              WHY: two different jobs (vectors
   ▼                                             vs. language) are optimized for
CHROMA vector DB (rag-data volume)                different hardware and libs
                                              WHY: docs need a searchable index;
   ▼                                             separate DB = persistent, scalable
STORAGE / CLUSTER (GKE nodes, ingress,        WHY: containers are ephemeral, so
   Artifact Registry, Terraform)                   durable data, images, and IaC
                                                   give stability, reuse, and code review
```

### 1. The gateway — why add it
**Why:** clients should never depend on individual backend URLs or the served
model name. If you later swap vLLM for Ollama (or add a third backend), the
client keeps calling `/chat` and never notices. It also gives you ONE place to
enforce an API key, rate limits, and logging.

### 2. The RAG service — why add it
**Why:** retrieval (embed + search Chroma + build a grounded prompt) is a full
algorithmic chain. Isolating it as its own service lets it scale independently
and keeps the gateway tiny. It shares the LLM and the embedding endpoints, so no
duplicate compute.

### 3. The embedding server (TEI) — why add it
**Why:** RAG must turn text into vectors, and the SAME model must be used at
ingest-time and query-time. A dedicated embedding server guarantees a single,
stable embedding model (`BAAI/bge-small-en-v1.5`) for all stages. Without this
consistency, retrieval returns unrelated chunks.

### 4. The LLM server (Ollama/vLLM) — why add it
**Why:** a RAG system still needs a language model to write the final answer.
Running it in-cluster (instead of an external API) keeps prompts/sensitive docs
internal. Both backends expose an OpenAI-compatible API so callers never change.

### 5. Chroma vector database — why add it
**Why:** plain text search fails on meaning ("I lost my password" ≠ "password").
Embeddings + a vector index give semantic search. Persisting it on a shared,
read-write-many volume (`rag-data`) lets the ingest job write and the service
read at the same time, and survive restarts.

### 6. Persistent storage (PVCs) — why add it
**Why:** containers are throwaway. Model weights (hundreds of MB/GB), the vector
DB, and source docs must survive pod restarts. Without PVCs every restart would
re-download models and lose your index.

### 7. Cluster + nodes — why add it
**Why:** deployment, scaling, self-healing, and rolling updates are handled by
GKE. Node pools separate CPU workloads from the (future) GPU pool so pasting a
GPU upgrade cannot affect CPU services.

### 8. Ingress / LoadBalancer — why add it
**Why:** a stable public address that load-balances across healthy gateway pods.
The load balancer health-checks backend instances so unhealthy nodes are taken
out of rotation automatically.

## Design rules this architecture follows
- **Single entry:** clients reach only the gateway.
- **OpenAI-compatible seams:** swapping backends changes config, never code.
- **Shared store**: one Chroma volume, one collection (`knowledge_base`), two
  writers (ingest) and readers (service).
- **Fail-safe storage classes**: `premium-rwo` where one pod reads/writes;
  `nfs-filestore` (RWX) where multiple pods need the same volume.