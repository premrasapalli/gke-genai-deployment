# Deployment, Prerequisites & End-to-End Example

This file covers everything you need before deploying, how the infrastructure
is built, and a practical runbook from an empty project to a live RAG demo.

---

# Prerequisites — What You Must Have, and Why

Before you can deploy you need a set of accounts, tools, and permissions.

## 1. A Google Cloud project
Everything lives inside one project (`aiml-project-idp`): the cluster, images,
IP address, and storage. A project gives a clean expense/spend boundary and an
identity boundary.

## 2. Billing enabled and linked
Compute, storage, and the load balancer cost money. If no billing account is
linked, actions like `terraform apply` fail later with confusing quota/denial
errors.

## 3. `gcloud` CLI + authentication
Terraform, `kubectl` and every `gcloud ...` command authenticate through your
user account. Check with `gcloud auth list`; set the project with
`gcloud config set project aiml-project-idp`.

## 4. `kubectl` + a working cluster context
`kubectl` is the CLI that drives Kubernetes. All deployments, logs, PVC
inspection, and port-forwarding happen through it.

```bash
gcloud container clusters get-credentials genai-cluster --region us-central1
kubectl config current-context   # should print the genai cluster
```

## 5. Terraform
The cluster, node pools, Artifact Registry, VPC, and static IP are declared as
code in `terraform/`. Terraform applies exactly the diff you reviewed (`plan`
before `apply`).

## 6. Docker (for local builds only)
Used for reproducing image builds locally. Note: local `docker build` on Apple
Silicon produces arm64 images that GKE (amd64) refuses with `exec format error`
— so final images are always built via Cloud Build (x86).

## 7. Quotas — the one that bites
Every GPU/CPU/regional resource has a project quota:

```bash
gcloud compute regions describe us-central1 \
  --format='table(quotas[].metric,quotas[].limit,quotas[].usage)'
```

In this project the global GPU quota `GPUS_ALL_REGIONS` was **0**, and L4 GPUs
were only available in `us-central1-a/b/c`. Check quotas BEFORE you design for
GPUs.

## 8. An Artifact Registry repo (created by Terraform)
Built images are pushed to `us-central1-docker.pkg.dev/aiml-project-idp/genai`.
Without it the image push and the node pulls both fail.

## 9. The node service account with pull rights
The cluster's nodes pull images using the workload identity service account.
Grant it `roles/artifactregistry.reader`.

## 10. Source documents (for RAG)
RAG is only useful with real content. The docs in this repo double as both the
manual AND the RAG knowledge base.

---

# Deploying on GKE with Terraform and Kustomize

## The layers

```
┌─────────────────────────────────────────────┐
│ GKE cluster genai-cluster (us-central1)     │
│  ├─ cpu-pool    3 × e2-standard-8 (CPU)     │
│  └─ gpu-pool    (disabled: L4 quota)        │
│                                             │
│  namespace genai                            │
│   ├─ gateway:1.0.0        (2 replicas)      │
│   ├─ rag-service:1.0.0                      │
│   ├─ serving-llm:1.0.0    (Ollama)          │
│   ├─ serving-embedding:1.0.0 (TEI)          │
│   └─ rag-ingest (CronJob)                   │
└─────────────────────────────────────────────┘
```

## Terraform (`terraform/`)

| File            | Contents                                     |
| --------------- | -------------------------------------------- |
| `providers.tf`  | Google provider + variables (`region`, `gpu_zone`, `enable_gpu_pool`, ...) |
| `main.tf`       | VPC network, GKE cluster, node pools, artifact repository, static IP |
| `backend.tf`    | GCS bucket that stores the remote state       |
| `terraform.tfvars` | Variable values actually applied          |

Key commands:

```bash
terraform init
terraform plan          # preview changes
terraform apply         # apply them
terraform output        # show endpoints (cluster_endpoint, gateway_static_ip)
```

By default the GPU pool is **off** (`enable_gpu_pool = false`). Turning it on
requires a `GPUS_ALL_REGIONS` quota increase in Google Cloud.

## Container images (`cloudbuild.yaml`)

Images are built for `linux/amd64` and stored in Artifact Registry:

```bash
gcloud builds submit --region=us-central1 --config=cloudbuild.yaml .
```

Build machines are x86, so they always produce amd64 images. The cluster's
service account has `roles/artifactregistry.reader` so nodes may pull these
images.

## Kubernetes manifests (`k8s/`)

```
k8s/base/        all resources: deployments, services, PVCs, ingress,
                 storage class, cronjob
k8s/overlays/    environment-specific tweaks on top of base
```

Apply (from the repo root):

```bash
kubectl apply -k k8s/base
kubectl -n genai rollout status deploy/gateway deploy/rag-service \
  deploy/serving-llm deploy/serving-embedding
```

Important wiring notes:

- **Storage classes**: `premium-rwo` for single-node access (model-store,
  embed-store), and `nfs-filestore` (Filestore CSI) for shared read-write-many
  access (rag-data).
- The **imagePullPolicy is `Always`** so that a rebuild+pull picks up changes
  even when the tag stays `1.0.0`.
- Model weights live on a volume mounted by `model-loader` and are not
  re-downloaded every boot once present.

## Changing something / recreating the cluster

1. Edit Terraform; `terraform plan`; `terraform apply`.
2. If the state is locked:
   ```bash
   terraform force-unlock <lock-id>
   ```
3. Node pools and the cluster can be deleted and recreated without touching
   the app code; storage volumes are persistent and survive cluster rebuilds.

---

# End-to-End Example: From an Empty Project to a Grounded RAG Demo

## 0. Prerequisites (once)

- `gcloud` logged in and billing linked on the project.
- `kubectl` configured for the cluster:
  ```bash
  gcloud container clusters get-credentials genai-cluster --region=us-central1 --project=aiml-project-idp
  ```

## 1. Build and deploy the app

```bash
gcloud builds submit --region=us-central1 --config=cloudbuild.yaml .
kubectl apply -k k8s/base
kubectl -n genai wait --for=condition=ready pod -l app=serving-llm --timeout=300s
kubectl -n genai get pods
```

Wait until all workload pods report `1/1 Running`:

```
gateway-xxxxxxxxxx-ccccc            2/2     Running
rag-service-xxxxxxxxxx-ccccc        1/1     Running
serving-llm-xxxxxxxxxx-ccccc        1/1     Running
serving-embedding-xxxxxxxxxx-ccccc  1/1     Running
```

## 2. Check the health of the stack

```bash
kubectl port-forward -n genai svc/gateway 8080:80 >/dev/null & PF=$!
sleep 5
curl -s localhost:8080/healthz      # -> {"status":"ok"}
curl -s localhost:8080/models       # -> qwen2.5:0.5b
kill $PF
```

## 3. Seed documents and ingest

```bash
R=$(kubectl get pod -n genai -l app=rag-service -o jsonpath='{.items[0].metadata.name}')
kubectl cp local-data/docs/intro.md genai/$R:/data/docs/

kubectl create job --from=cronjob/rag-ingest rag-ingest-manual -n genai
kubectl wait --for=condition=complete job/rag-ingest-manual -n genai --timeout=300s
kubectl logs -n genai job/rag-ingest-manual --tail=5
```

Expect: `Ingested ... -> N chunks` and `Done. Total chunks: N`.

## 4. Verify the vector store persisted

```bash
R=$(kubectl get pod -n genai -l app=rag-service -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n genai "$R" -- python -c "from config import get_store; print(get_store()._collection.count())"
kubectl exec -n genai "$R" -- ls /data/chroma
```

You should see a non-zero count and a `chroma.sqlite3` file.

## 5. Ask grounded questions

```bash
kubectl port-forward -n genai svc/gateway 8080:80 >/dev/null & PF=$!
sleep 5
curl -s -X POST localhost:8080/rag \
  -H 'Content-Type: application/json' \
  -d '{"query":"What endpoints does the API gateway expose?"}'
kill $PF
```

A healthy answer quotes the gateway's actual endpoints (`/healthz`, `/models`,
`/chat`, `/rag`) and cites the context — proof the model read your document.
