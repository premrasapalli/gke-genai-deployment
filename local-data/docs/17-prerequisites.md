# Prerequisites — What You Must Have, and Why Each One

Before you can deploy you need a set of accounts, tools, and permissions. This
list explains every prerequisite and **why you must add it** — so you never pull
your hair out later wondering "why is this here?".

## 1. A Google Cloud project — why
Everything lives inside one project (`aiml-project-idp`): the cluster, images,
IP address, and storage. A project gives a clean expense/spend boundary and an
identity boundary. **Why add it:** without a project there is no Google Cloud at
all — it is the top-level container for every resource you create.

## 2. Billing enabled and linked — why
Compute, storage, and the load balancer cost money. If no billing account is
linked, actions like `terraform apply` fail later with confusing quota/denial
errors. **Why add it now:** you can fix it before anything else breaks; we got
burned by a disabled billing account that blocked creating GPUs.

## 3. `gcloud` CLI + authentication — why
Terraform, `kubectl` and every `gcloud ...` command authenticate through your
user account. **Why add it:** without it you cannot talk to GCP from your
machine at all. Check with `gcloud auth list`; set the project with
`gcloud config set project aiml-project-idp`.

## 4. `kubectl` + a working cluster context — why
`kubectl` is the CLI that drives Kubernetes. **Why add it:** all deployments,
logs, PVC inspection, and port-forwarding happen through it. Get the context
with:

```bash
gcloud container clusters get-credentials genai-cluster --region us-central1
kubectl config current-context   # should print the genai cluster
```

## 5. Terraform — why
The cluster, node pools, Artifact Registry, VPC, and static IP are declared as
code in `terraform/`. Terraform applies exactly the diff you reviewed (`plan`
before `apply`). **Why add it:** reproducible infrastructure — no one clicks
around the console and forgets a setting; a teammate can recreate the cluster
from the repo.

## 6. Docker (for local builds only) — why
Used for reproducing image builds locally. **Why add it:** rapid debugging.
Note: local `docker build` on Apple Silicon produces arm64 images that GKE
(amd64) refuses with `exec format error` — so final images are always built via
Cloud Build (x86) as documented in the CI/CD file.

## 7. Quotas — the one that bites — why
Every GPU/CPU/regional resource has a project quota. **Why check it first:**

```bash
gcloud compute regions describe us-central1 \
  --format='table(quotas[].metric,quotas[].limit,quotas[].usage)'
```

In this project the global GPU quota `GPUS_ALL_REGIONS` was **0**, and L4 GPUs
were only available in `us-central1-a/b/c`. So the platform went live CPU-only
now, with the GPU pool declared but disabled and a quota-increase request filed.
Check quotas BEFORE you design for GPUs.

## 8. An Artifact Registry repo (created by Terraform) — why
Built images are pushed to `us-central1-docker.pkg.dev/aiml-project-idp/genai`.
**Why add it:** it is the registry the cluster pulls from; without it the image
push and the node pulls both fail (we saw the first deploy 403 on the empty repo).

## 9. The node service account with pull rights — why
The cluster's nodes pull images using the workload identity service account.
If it cannot read the registry, every pod dies with `ImagePullBackOff`. Grant it
`roles/artifactregistry.reader` **— why add it:** nodes authenticate as this SA;
a permission gap here fails the whole cluster even though code is fine.

## 10. Source documents (for RAG) — why
RAG is only useful with real content. We keep 15+ Markdown files that explain
the platform itself. **Why add it:** retrieval needs something to retrieve; the
docs in this repo double as both the manual AND the RAG knowledge base.