# All Services — Each One, What It Does, and Why It Is Used

A complete, boringly-thorough inventory of every running component: what it is,
who talks to it, and — most importantly — **why it is used at all**. If a
component's "why" disappears, it is a candidate for removal.

## 1. gateway (Deployment, FastAPI, :80)
- **What:** public API door: `/chat`, `/rag`, `/models`, `/healthz`, and a
  browser UI at `/`.
- **Talks to:** serving-llm (chat), rag-service (/rag), TEI indirectly.
- **Why it is used:** a single stable entry point so clients never know the
  cluster internals; one place for auth (optional `API_KEY`), validation, and
  logging.

## 2. rag-service (Deployment, FastAPI, :8080)
- **What:** runs the answer chain: embed query → retrieve top-k chunks from
  Chroma → build grounded prompt → call the LLM → return `{answer}`.
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
- **What:** compute for everything (cpu-pool: 3× e2-standard-8); gpu-pool is
  declared, disabled by quota.
- **Why:** separates CPU workloads and (future) GPU workloads; a GPU change
  could then not disturb CPU services.

## 16. Monitoring, secrets, and namespaces
- **What:** `monitoring/` for alerts; `gateway-secret`, `hf-secret` for keys;
  the `genai` namespace isolates everything.
- **Why:** alert on failures, keep keys out of pods/env, and give every
  resource a home one `kubectl -n genai` away.