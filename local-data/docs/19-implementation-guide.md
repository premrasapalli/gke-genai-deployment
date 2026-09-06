# Implementation — Step by Step to Make It Live (and why, at each step)

This is the exact order of operations used to bring this platform from nothing
to a live public URL. Every step includes **why you add it** so you can extend
or repair the system, not just replay it.

## Phase A — Infrastructure (Terraform)

### A1. Create the VPC, cluster, node pools, registry, static IP. Why?
Declaring them in `terraform/` makes the cloud reproducible. Apply from the
repo:

```bash
terraform plan        # preview; never apply blind
terraform apply
```

### A2. CPU-only now, GPU pool declared but disabled. Why?
`enable_gpu_pool = false` in `terraform.tfvars` — the global GPU quota is 0, so
a GPU pool would repeatedly fail to provision. Keeping its config in Terraform
means flipping it on later is one change. (GPU nodes are L4 only in
us-central1-a/b/c, so `node_locations` pins `gpu_zone`.)

## Phase B — Registry access

### B1. Build and push images. Why?
`gcloud builds submit --region=us-central1 --config=cloudbuild.yaml .` builds
`gateway`, `rag`, `model-loader` as amd64 into Artifact Registry. Cloud Build's
x86 runners guarantee the architecture GKE needs (`exec format error` avoided).

### B2. Grant nodes pull rights. Why?
The cluster nodes act as `genai-gke@aiml-project-idp.iam.gserviceaccount.com`.
Without `roles/artifactregistry.reader`, every pod lands in `ImagePullBackOff`.

```bash
gcloud projects add-iam-policy-binding aiml-project-idp \
  --member="serviceAccount:genai-gke@aiml-project-idp.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.reader
```

## Phase C — Storage classes and PVCs

### C1. Create storage classes. Why?
K8s PVCs need a class: `premium-rwo` (SSD, single-writer) for model & embed
volumes; `nfs-filestore` (Filestore CSI, `basic-hdd`) for shared RWX. **Why a
separate class:** the RAG data must be read and written by DIFFERENT pods at
the same time — only a read-write-many volume supports that.

### C2. Create PVCs: model-store, embed-store, rag-data. Why?
`rag-data` (RWX, Filestore) holds both the Chroma DB and the `docs/` folder;
model + embed stores keep weights local and fast on premium-rwo.

## Phase D — Deploy workloads (Kustomize)

### D1. Apply the base manifest set. Why?
`kubectl apply -k k8s/base` creates namespace, secrets, services,
deployments, cronjob, ingress, PVCs, and storage class in one declarative pass.

### D2. Apply the prod overlay. Why?
Base uses short names like `genai/gateway:1.0.0`. The overlay rewrites them to
the full registry path (`images:` kustomize transformer). If you apply base
without the overlay, pods try to pull `docker.io/genai/gateway` and fail with
`ImagePullBackOff`. **Implemented via:** `kubectl apply -k k8s/overlays/prod`.

## Phase E — Get a public URL

### E1. LoadBalancer service. Why?
The GCE Ingress controller did not provision a load balancer, so we exposed the
gateway with a classic `type: LoadBalancer` service, which the cloud provider
fulfills reliably.

```bash
kubectl -n genai create service loadbalancer gateway-lb --tcp=80:8080 \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n genai get svc gateway-lb   # copy EXTERNAL-IP (e.g. 34.63.204.167)
```

### E2. Verify health from the public URL. Why?
The IP is useless until `GET /healthz` answers `{"status":"ok"}`. Also confirm
the backend instances show HEALTHY in the target pool.

## Phase F — Seed the RAG knowledge base

### F1. Upload source docs to GCS. Why?
The cronjob's `seed-docs` initContainer rsyncs `DOCS_GCS_URI` into `/data/docs`.
GCS gives a durable, versionable doc source instead of `kubectl cp` races.

```bash
gcloud storage buckets create gs://aiml-project-idp-rag-docs --location=us-central1
gcloud storage cp -r local-data/docs gs://aiml-project-idp-rag-docs/docs
gsutil iam ch serviceAccount:genai-gke@aiml-project-idp.iam.gserviceaccount.com:objectViewer gs://aiml-project-idp-rag-docs
```

### F2. Run a manual ingest. Why?
So the index exists immediately (the 6-hourly cronjob is the safety net). The
job embeds each chunk via TEI and writes into `knowledge_base` on the shared
volume. Verify persistence (see troubleshooting): on-disk
`/data/chroma/chroma.sqlite3` must exist and the collection count must be > 0.

### F3. Optionally wrap in `.env`, CI, or schedule. Why?
Automate what is deterministic: seed step in CI when docs change, and a cronjob
re-ingest every 6h to absorb edits automatically.

## Phase G — Smoke test the live contract. Why?
A "deployed" system is only done when its API contract is proven from outside:

```bash
curl http://<IP>/healthz                       # {"status":"ok"}
curl -X POST http://<IP>/chat -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Say hello"}]}'
curl -X POST http://<IP>/rag -H 'Content-Type: application/json' \
  -d '{"query":"What is RAG?"}'
```

Every phase exists because the previous one left a gap: infra before cluster,
registry before pull, PVs before data, overlay before images, LB before URL,
docs+GCS before RAG, and the smoke test before you call it done.