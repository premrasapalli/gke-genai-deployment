# GKE GenAI Deployment — Model Serving · Inference · RAG

An end-to-end LLM/GenAI deployment stack for Google Cloud (GKE):

- **Model serving** — vLLM (OpenAI-compatible) for the LLM, Text Embeddings
  Inference (TEI) for embeddings. Models auto-download into a shared volume.
- **RAG pipeline** — Chroma vector DB, document ingestion (CronJob), retrieval
  and a grounded-answer chain.
- **API gateway** — FastAPI exposing `/chat`, `/rag`, `/models`, `/healthz`.
- **GitOps-ready K8s manifests** — Kustomize `base` deployable via ArgoCD.
- **Terraform IaC** — GKE cluster (CPU + GPU pools) and Artifact Registry.

## Architecture

```
                        ┌──────────────┐
   Ingress ──►  Gateway  ──►  serving-llm (vLLM, :8000 /v1)
   (/chat,/rag)          │      └── model-store PVC (HF download initContainer)
                        │  ──►  serving-embedding (TEI, :8001 /v1)
                        │  ──►  rag-service (:8080 /answer)
                        │         └── Chroma (rag-data PVC)
                        └── ──►  rag-ingest (CronJob, every 6h)
```

Query flow for RAG: user → `/rag` → retriever embeds query via TEI, top-k chunks
from Chroma → vLLM prompt with grounded context → answer.

## 1. Local bring-up (Docker Compose)

```bash
docker compose up --build -d
docker compose exec ingest python -m ingest --dir /data/docs   # index local-data/docs

curl http://localhost:8080/healthz
curl -X POST http://localhost:8080/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"What is RAG in one sentence?"}]}'
curl -X POST http://localhost:8080/rag \
  -H 'Content-Type: application/json' -d '{"query":"What does the gateway do?"}'
```

## 2. Provision GCP infra (Terraform)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id
gcloud auth application-default login
terraform init
terraform plan
terraform apply
```

Creates `genai-cluster` (e2-standard-8 CPU pool + g2-standard-12 GPU pool with
L4) and `genai` Artifact Registry. For CPU-only bring-up, comment out the `gpu`
pool or apply with `-var` overrides.

```bash
gcloud container clusters get-credentials genai-cluster --region us-central1
```

## 3. Build & push images (Artifact Registry)

```bash
export REGION=us-central1; export PROJECT_ID=<gcp-project>
gcloud auth configure-docker $REGION-docker.pkg.dev

docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/genai/model-loader:1.0.0 serving/ -f serving/Dockerfile.model-loader
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/genai/rag:1.0.0 rag/
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/genai/gateway:1.0.0 gateway/

# vLLM and TEI are pulled from upstream but you can mirror them too:
docker pull vllm/vllm-openai:latest
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5
```

## 4. Deploy to GKE (Kustomize / GitOps)

Replace `<PROJECT_ID>` in `k8s/base/` image references (or use an overlay), then:

```bash
kubectl apply -k k8s/base
# or with ArgoCD:
argocd app create genai --repo https://github.com/premrasapalli/gke-genai-deployment.git \
  --path k8s/base --dest-server https://kubernetes.default.svc --dest-namespace genai \
  --sync-policy automated --self-heal --prune
```

Verify:

```bash
kubectl get pods -n genai -w          # wait: serving-llm initContainer downloads model
kubectl port-forward -n genai svc/gateway 8080:80
curl http://localhost:8080/chat -X POST -d '{"messages":[{"role":"user","content":"hi"}]}' -H 'Content-Type: application/json'
```

The first model download can take a few minutes depending on model size.

## 5. Embeddings note

The project defaults to `BAAI/bge-small-en-v1.5` via TEI on port 8001 with an
OpenAI-compatible `/v1/embeddings`. Keep the embedding model consistent between
ingestion and query time (env `EMBEDDING_MODEL`).

## Configuration quick reference

| Component | Env | Default |
|-----------|-----|---------|
| Gateway  | `LLM_URL`, `LLM_MODEL`, `RAG_URL` | vLLM :8000/v1, `genai-model`, rag-service :8080 |
| RAG      | `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `LLM_BASE_URL`, `RAG_PERSIST_DIR` | TEI :8001/v1, `bge-small-en-v1.5`, vLLM :8000/v1, /data/chroma |
| vLLM     | `HF_MODEL` (initContainer) | `Qwen/Qwen2.5-0.5B-Instruct` |