# CI/CD Pipeline — How Changes Reach the Running Platform

CI/CD stands for **Continuous Integration** and **Continuous Deployment**. It is
the automated pipeline that takes a code change, tests it, builds it, ships it,
and puts it live — with as little human clicking as possible.

## The pipeline at a glance

```
1 push/PR  ->  2 WIF auth  ->  3 lint+test  ->  4 build amd64  ->  5 push images
                                                                    |
6 apply manifests (kubectl)  <--  ArgoCD/GitOps also possible  <----+
7 rolling update + probes  ->  8 health check  ->  9 done, rollback possible
```

Everything is driven by **GitHub Actions** (the CI part) plus either **kubectl**
or **ArgoCD** (the CD part). Git is the single source of truth: whatever is in
the repository is what should be running.

---

## Step 1 — Trigger (push / pull request). Why?

When you push to the repository, GitHub Actions detects the event and starts a
workflow defined in `.github/workflows/build-push.yml`. Every deploy must start
from an explicit event so changes are traceable to a commit.

**Why:** without a trigger, deployments are manual, unrepeatable, and nobody can
say "what version is live?".

## Step 2 — Workload Identity Federation (WIF). Why?

The pipeline must authenticate to GCP without storing a secret in the repo.
WIF lets GitHub exchange its OIDC token for short-lived Google credentials. The
workflow config provides:

- `PROJECT_ID` — `aiml-project-idp`
- `WIF_PROVIDER` — the identity provider resource
- `WIF_SERVICE_ACCOUNT` — the service account with permission to write images

**Why:** no long-lived service-account key to rotate, leak, or revoke.

## Step 3 — Lint + tests. Why?

Catch breakage before it ships into a shared cluster. Example: the gateway
PyData/CORS, config sanity, response-model checks.

**Why:** a test caught early costs seconds; the same bug caught live costs a
rollback and support.

## Step 4 — Build `linux/amd64` images. Why?

The pipeline builds three first-party images:

- `genai/gateway` — the API gateway
- `genai/rag` — the RAG service and ingest job
- `genai/model-loader` — downloads models into the shared volume

GKE nodes are x86. If you build on an Apple Silicon laptop and forget
`--platform linux/amd64`, the image will not run on the cluster's amd64 nodes
(you get the famous `exec format error`). Cloud Build runs on x86 machines, so
the artifact is always the target architecture.

## Step 5 — Push to Artifact Registry. Why?

Images are pushed to Google **Artifact Registry**:

```
us-central1-docker.pkg.dev/aiml-project-idp/genai/<name>:1.0.0
```

Images are **versioned** (e.g. `1.0.0`) rather than using `:latest`, because
versioned tags make builds reproducible and make rollbacks possible.

**Why:** a registry is how nodes get images at all; versioned tags are how you
can revert safely.

## Step 6 — Apply the Kubernetes manifests. Why?

Once images exist in Artifact Registry, the running cluster needs to start using
the new versions. Two modes:

- **Manual kubectl** — run `kubectl apply -k k8s/overlays/prod` to apply the
  Kubernetes manifests. This is great for development and for a demo.
- **ArgoCD (GitOps)** — a controller inside the cluster continuously watches
  the git repo and automatically reconciles the cluster to match it.

**Why:** deployment = telling Kubernetes the desired state; without this step new
images are pushed but never used.

## Step 7 — Rolling update with probes. Why?

When new pod definitions reach the cluster, Kubernetes performs a **rolling
update**:

1. A new ReplicaSet is created with the new pod definition.
2. It starts a new pod with the new image.
3. Readiness probes (`/healthz`, `/api/tags`, etc.) are used to check the new
   pod is actually healthy.
4. Only then is an old pod terminated.

Because we set `imagePullPolicy: Always` on our app containers, each new pod
pulls the exact latest `1.0.0` tag rather than reusing a cached copy.

**Why:** zero downtime and no "half-mixed" traffic; a failing new pod blocks the
rollout instead of taking the service down.

## Step 8 — Post-deploy health verification. Why?

Confirm the live URL answers: `GET /healthz` -> ok, `/chat` and `/rag` return.

**Why:** green ICMP to a pod ≠ a working RAG chain; verify the contract.

## Step 9 — Rollback path. Why?

Because deployments fail, the pipeline must define how to revert: point back at
a previous image tag or previous commit.

- If a new pod fails its readiness probe repeatedly, Kubernetes stops the
  rollout (it does not keep destroying healthy pods) and reports the pod state
  like `CrashLoopBackOff`.
- Because images and manifests are versioned and stored, you can roll back to a
  previous image tag or a previous git commit.
- Monitoring (see the `monitoring/` directory) raises alerts if a workload goes
  down or a node becomes unhealthy, so problems are caught automatically.

**Why:** a documented rollback converts a potential outage into a minutes-long
fix.

---

## Summary: the end-to-end life of a change

1. Developer edits code and commits.
2. GitHub Actions builds and pushes new `1.0.0` images (WIF auth, no secrets).
3. The change is merged and the manifests are applied (kubectl) — or ArgoCD
   auto-syncs from git.
4. Kubernetes rolls out new pods, verifying health with probes.
5. The gateway's `/healthz` reports the system is healthy; users call `/chat`
   and `/rag` as normal.

## What actually happened in this project (worked example)

1. We edited `rag/requirements.txt` (chromadb pin) and pushed.
2. Cloud Build rebuilt `genai/rag:1.0.0` for amd64 and pushed it.
3. `kubectl rollout restart deploy/rag-service` (imagePullPolicy: `Always`) made
   new pods pull the fresh tag.
4. Readiness probes confirmed the new pod healthy; old pod retired.
5. A manual ingest job re-indexed the docs with the new library.

That sequence — build -> push -> restart -> probe -> verify — is the CI/CD flow
in miniature, and each building block exists only because the previous one had a
specific GAP it filled.
