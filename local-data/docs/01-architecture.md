# Architecture — Structure, Rationale & Service Inventory

This document maps the whole platform: the moving parts, how the data flows,
why each layer exists, and a complete inventory of every running component. Read
this first to build a mental model, then use the other files for the details.

## The layers (and why each exists)

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
Clients should never depend on individual backend URLs or the served model name.
If you later swap vLLM for Ollama (or add a third backend), the client keeps
calling `/chat` and never notices. It also gives you ONE place to enforce an API
key, rate limits, and logging.

### 2. The RAG service — why add it
Retrieval (embed + search Chroma + build a grounded prompt) is a full
algorithmic chain. Isolating it as its own service lets it scale independently
and keeps the gateway tiny. It shares the LLM and the embedding endpoints, so no
duplicate compute.

### 3. The embedding server (TEI) — why add it
RAG must turn text into vectors, and the SAME model must be used at ingest-time
and query-time. A dedicated embedding server guarantees a single, stable
embedding model (`BAAI/bge-small-en-v1.5`) for all stages. Without this
consistency, retrieval returns unrelated chunks.

### 4. The LLM server (Ollama/vLLM) — why add it
A RAG system still needs a language model to write the final answer. Running it
in-cluster (instead of an external API) keeps prompts/sensitive docs internal.
Both backends expose an OpenAI-compatible API so callers never change.

### 5. Chroma vector database — why add it
Plain text search fails on meaning ("I lost my password" ≠ "password").
Embeddings + a vector index give semantic search. Persisting it on a shared,
read-write-many volume (`rag-data`) lets the ingest job write and the service
read at the same time, and survive restarts.

### 6. Persistent storage (PVCs) — why add it
Containers are throwaway. Model weights (hundreds of MB/GB), the vector DB, and
source docs must survive pod restarts. Without PVCs every restart would
re-download models and lose your index.

### 7. Cluster + nodes — why add it
Deployment, scaling, self-healing, and rolling updates are handled by GKE. Node
pools separate CPU workloads from the (future) GPU pool so pasting a GPU upgrade
cannot affect CPU services.

### 8. Ingress / LoadBalancer — why add it
A stable public address that load-balances across healthy gateway pods. The load
balancer health-checks backend instances so unhealthy nodes are taken out of
rotation automatically.

## The data flows

**Chat path (no documents):**
`client -> gateway -> LLM -> gateway -> client`

**RAG path (grounded in documents):**
`client -> gateway -> rag-service -> embedding(TEI) -> Chroma retrieval
         -> rag-service -> LLM -> gateway -> client`

**Ingestion path (offline):**
`docs (/data/docs or GCS) -> chunk + embed(TEI) -> store in Chroma (rag-data)`

## Storage decisions

| Data | Where | Why |
|------|-------|-----|
| LLM weights | `model-store` (premium-rwo, SSD, RWO) | Fast, single writer (the LLM pod) |
| Embedding model | `embed-store` (premium-rwo) | TEI loads it locally |
| Chroma vectors + docs | `rag-data` (Filestore, RWX) | Shared by rag-service (reads) and ingest (writes) simultaneously |

The RWO/RWX distinction is the key lesson: any data shared by two pods at once
must be on a read-write-many volume.

## Infrastructure that binds it together

- **GKE cluster** (`genai-cluster`) hosts every deployment.
- **Node pools** — `cpu-pool` for current workloads; `gpu-pool` (L4) reserved
  for larger models once GPU quota is granted.
- **Artifact Registry** stores the built images; the cluster pulls from it.
- **Ingress + static IP** — a reserved global IP fronts the gateway, providing
  a stable external address and HTTP load balancing.
- **Terraform** declares the cluster, pools, registry, and IP; **k8s manifests**
  declare the workloads.

## Request lifecycle with Kubernetes

1. A request arrives at the Ingress (static IP) and is routed to the gateway
   Service.
2. Kubernetes load-balances across gateway pods.
3. The gateway calls other services over their stable DNS names.
4. Each service is kept healthy by readiness/liveness probes; if one crashes,
   Kubernetes restarts or reschedules it.

## Design rules

- **Single entry:** clients reach only the gateway.
- **OpenAI-compatible seams:** swapping backends changes config, never code.
- **Shared store**: one Chroma volume, one collection (`knowledge_base`), two
  writers (ingest) and readers (service).
- **Fail-safe storage classes**: `premium-rwo` where one pod reads/writes;
  `nfs-filestore` (RWX) where multiple pods need the same volume.

---

# Complete Service Inventory

A thorough inventory of every running component: what it is, who talks to it,
and why it is used.

## 1. gateway (Deployment, FastAPI, :80)
- **What:** public API door: `/chat`, `/rag`, `/models`, `/healthz`, and a
  browser UI at `/`.
- **Talks to:** serving-llm (chat), rag-service (/rag), TEI indirectly.
- **Why:** a single stable entry point so clients never know the cluster
  internals; one place for auth (optional `API_KEY`), validation, and logging.

## 2. rag-service (Deployment, FastAPI, :8080)
- **What:** runs the answer chain: embed query -> retrieve top-k chunks from
  Chroma -> build grounded prompt -> call the LLM -> return `{answer}`.
- **Talks to:** serving-embedding, Chroma (on `rag-data`), serving-llm.
- **Why:** retrieval is a separate, scaling concern; isolating it keeps the
  gateway thin and testable.

## 3. serving-llm (Deployment — Ollama :8000 / vLLM :8000)
- **What:** hosts the language model. Currently Ollama serving `qwen2.5:0.5b`
  (OpenAI-compatible `/v1/chat/completions`). The GPU path would use vLLM with
  `genai-model`.
- **Talks to:** anyone calling its OpenAI-compatible API (gateway, rag-service).
- **Why:** self-hosting keeps prompts and documents in-cluster; the
  OpenAI-compatible seam makes backend swaps a config change, not a code change.

## 4. serving-embedding (Deployment — TEI, :8001)
- **What:** exposes `/embeddings` for one model (`BAAI/bge-small-en-v1.5`),
  providing 384-dim vectors.
- **Talks to:** rag-service + rag-ingest at both ingest and query time.
- **Why:** a dedicated, consistent embedder is what makes semantic retrieval
  work; the same model in both phases is why results are meaningful.

## 5. rag-ingest (CronJob, every 6h)
- **What:** seeds `/data/docs` from a GCS bucket (`seed-docs` initContainer)
  then embeds + upserts all `.md`/`.txt` chunks into the Chroma collection
  `knowledge_base` on `/data/chroma`.
- **Why:** documents change; the vector index must track them. Scheduled
  ingestion keeps the knowledge base fresh without manual work.

## 6. Chroma vector database (on `rag-data` PVC)
- **What:** a local, SQLite-backed vector store holding ~122 chunks across 16
  documents today.
- **Why:** semantic search over chunks — the mechanism that makes grounded
  RAG answers possible. Persisted on shared RWX storage so it survives restarts.

## 7. model-store / embed-store (PVCs, premium-rwo)
- **What:** durable volumes for LLM weights and the embedding model.
- **Why:** avoid re-downloading multi-GB weights on every restart; SSD-backed,
  single-writer access is the right profile for "one pod owns the data".

## 8. rag-data (PVC — Filestore / NFS, RWX)
- **What:** shared volume holding `/data/docs` and `/data/chroma`.
- **Why:** read-write-many is the ONLY class that lets the batch write (ingest)
  and the online read (rag-service) coincide without RWO conflicts.

## 9. nfs-filestore (StorageClass)
- **What:** maps PVCs to a Google Filestore instance (tier `basic-hdd`) over
  NFS with the Filestore CSI driver.
- **Why:** GKE has no built-in RWX volume — Filestore is the managed way to
  get one for shared data.

## 10. gateway-lb (Service, type: LoadBalancer)
- **What:** the public TCP load balancer in front of the gateway
  (external IP `34.63.204.167`).
- **Why:** a reachable-from-the-internet address that health-checks the nodes
  and only routes to healthy ones.

## 11. genai-gateway Ingress (declared but stalled)
- **What:** the GCE Ingress intended to front the gateway plus the reserved
  global static IP `136.68.152.87`.
- **Why attempted:** a stable, product-style entry with a reserved IP.
  **State:** the GCE ingress controller has not provisioned forwarding rules —
  that is the open item to fix if you want the reserved IP instead of the LB's
  ephemeral one.

## 12. gateway / rag-service / serving-* ClusterIP Services
- **What:** in-cluster stable DNS + L4 load balancing per workload.
- **Why:** pods regenerate names/IPs constantly; services give fixed,
  human-readable addresses (`serving-llm`, `rag-service`, ...) that config
  files can rely on.

## 13. Artifact Registry repo `genai`
- **What:** stores `gateway:1.0.0`, `rag:1.0.0`, `model-loader:1.0.0` images.
- **Why:** the source of truth for images; nodes pull from here; versioned tags
  enable rollbacks.

## 14. model-loader (initContainer image)
- **What:** downloads models into the shared volume before the real container
  starts (used by serving-embedding and the LLM).
- **Why:** predictable readiness — new pods start only after weights exist
  locally instead of hammering Hugging Face on first boot.

## 15. GKE node pools (cpu-pool / gpu-pool)
- **What:** compute for everything (cpu-pool: 3x e2-standard-8); gpu-pool is
  declared, disabled by quota.
- **Why:** separates CPU workloads and (future) GPU workloads; a GPU change
  could then not disturb CPU services.

## 16. Monitoring, secrets, and namespaces
- **What:** `monitoring/` for alerts; `gateway-secret`, `hf-secret` for keys;
  the `genai` namespace isolates everything.
- **Why:** alert on failures, keep keys out of pods/env, and give every
  resource a home one `kubectl -n genai` away.
