# Architecture at a Glance

This file is a single, high-level map of the whole platform: the moving parts,
how the data flows, and how the infrastructure supports it. Read this one first
to build a mental model, then use the other files for the details.

## The layers

The platform separates into four layers, each with a clear responsibility:

1. **Clients / entry** — a frontend, CLI, or curl script.
2. **API gateway** — the single door into the system.
3. **AI services** — the LLM, the embedding server, and the RAG service.
4. **Storage & infrastructure** — vector database, model store, Kubernetes
   nodes, ingress, registry.

```
           ┌──────────────────────────────────────────────────────┐
           │                     CLIENTS                            │
           │         (browser / curl / app, via Ingress + static IP) │
           └───────────────────────────┬──────────────────────────┘
                                       │  /chat  /rag  /models  /healthz
                              ┌────────▼────────┐
                              │      GATEWAY     │   (FastAPI, :80)
                              └────────┬────────┘
                        ┌──────────────┼───────────────┐
                        │              │               │
                 ┌──────▼──────┐  ┌────▼─────┐   ┌─────▼────────┐
                 │  RAG SERVICE │  │  LLM     │   │  EMBEDDING   │
                 │  (FastAPI)   │  │ (Ollama/ │   │    (TEI)     │
                 │    :8080     │  │  vLLM)   │   │     :8001    │
                 └──────┬──────┘  │  :8000   │   └──────────────┘
                        │         └──────────┘
              ┌─────────▼──────────┐
              │   Chroma (vectors) │
              │  on rag-data (RWX) │        ┌─────────────────┐
              └─────────┬──────────┘        │  model-store    │
                        │ ingest writes     │  (premium-rwo)  │
              ┌─────────▼──────────┐        └─────────────────┘
              │    rag-ingest      │
              │   (CronJob)        │──docs from /data/docs or GCS
              └────────────────────┘
```

## The data flows

**Chat path (no documents):**
`client -> gateway -> LLM -> gateway -> client`

**RAG path (grounded in documents):**
`client -> gateway -> rag-service -> embedding(TEI) -> Chroma retrieval
         -> rag-service -> LLM -> gateway -> client`

**Ingestion path (offline):**
`docs (/data/docs or GCS) -> chunk + embed(TEI) -> store in Chroma (rag-data)`

## Storage decisions and why

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

## Where to learn more

- File `11-cicd.md` — how a code change flows to a running update.
- File `14-integration.md` — the exact service-to-service handoffs.
- Files 05-08 — the RAG details.
- File `10-deploying-on-gke.md` — nodes, pools, commands, and storage internals.
