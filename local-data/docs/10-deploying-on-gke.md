# Deploying on GKE with Terraform and Kustomize

This chapter walks a first-time reader through the infrastructure: how the
cluster was created, how to change it, and how to apply the app manifests.

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

Terraform owns the cloud resources:

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
requires a `GPUS_ALL_REGIONS` quota increase in Google Cloud, because the
project started with that quota at 0 (L4 GPUs are limited globally).

## Container images (`cloudbuild.yaml`)

Images are built for `linux/amd64` and stored in Artifact Registry
(`us-central1-docker.pkg.dev/aiml-project-idp/genai`):

- `gateway:1.0.0`
- `rag:1.0.0`
- `model-loader:1.0.0`

Build and push everything with one command:

```bash
gcloud builds submit --region=us-central1 --config=cloudbuild.yaml .
```

Build machines are x86, so they always produce amd64 images. Building locally
on an Apple Silicon Mac gives arm64 images, which the GKE node pool cannot run
(fixable with `--platform linux/amd64` or by using Cloud Build). The cluster's
service account `genai-gke@aiml-project-idp.iam.gserviceaccount.com` has
`roles/artifactregistry.reader` so nodes may pull these images.

## Kubernetes manifests (`k8s/`)

The app is organized with Kustomize:

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
  access (rag-data, shared by the service and the ingest job).
- The **imagePullPolicy is `Always`** so that a rebuild+pull picks up changes
  even when the tag stays `1.0.0`. After rebuilding, use
  `kubectl rollout restart deploy/<name>` to force new pods.
- Model weights live on a volume mounted by `model-loader` and are not
  re-downloaded every boot once present.

## Changing something / recreating the cluster

1. Edit Terraform; `terraform plan`; `terraform apply`. GKE upgrades are
   managed by Google.
2. If the state is locked (an earlier apply was interrupted), release it:
   ```bash
   terraform force-unlock <lock-id>
   ```
3. Node pools and the cluster can be deleted and recreated without touching
   the app code; storage volumes are persistent and survive cluster rebuilds.