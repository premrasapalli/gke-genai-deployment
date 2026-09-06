# CI/CD End-to-End Flow — Every Step and Why It Exists

CI/CD automates the journey from "code changed" to "new version live" with
nothing left to memory. Each step below is listed with **why you add that step**
so the pipeline reads like a checklist, not magic.

## The pipeline at a glance

```
1 push/PR  ->  2 WIF auth  ->  3 lint+test  ->  4 build amd64  ->  5 push images
                                                                    |
6 apply manifests (kubectl)  <--  ArgoCD/GitOps also possible  <----+
7 rolling update + probes  ->  8 health check  ->  9 done, rollback possible
```

---

### Step 1 — Trigger (push / pull request). Why?
Every deploy must start from an explicit event so changes are traceable to a
commit. A GitHub Actions workflow (`.github/workflows/build-push.yml`) fires on
push to `main`. **Why add it:** without a trigger, deployments are manual,
unrepeatable, and nobody can say "what version is live?".

### Step 2 — Workload Identity Federation (WIF). Why?
The pipeline must authenticate to GCP without storing a secret in the repo.
WIF lets GitHub exchange its OIDC token for short-lived Google credentials.
**Why add it:** no long-lived service-account key to rotate, leak, or revoke.

### Step 3 — Lint + tests. Why?
Catch breakage before it ships into a shared cluster. Example: the gateway
PyData/CORS, config sanity, response-model checks. **Why add it:** a test caught
early costs seconds; the same bug caught live costs a rollback and support.

### Step 4 — Build `linux/amd64` images. Why?
GKE nodes are x86. My development Mac is arm64. An arm64 image fails to run on
the cluster with `exec format error`. Cloud Build runs on x86 machines, so the
artifact is always the target architecture. **Why add it:** you do not want
someone's laptop architecture silently corrupting the deployment.

### Step 5 — Push to Artifact Registry. Why?
The registry is the single source of the images the cluster pulls. Versioned
tags (`1.0.0`) make every image reproducible and every rollback possible.
**Why add it:** a registry is how nodes get images at all; versioned tags are
how you can revert safely.

### Step 6 — Apply the Kubernetes manifests. Why?
The running cluster must be told to use the new images/tags. Two modes:
- manual `kubectl apply -k k8s/overlays/prod`
- GitOps (ArgoCD watches the repo and auto-applies on change)

**Why add it:** deployment = telling Kubernetes the desired state; without this
step new images are pushed but never used.

### Step 7 — Rolling update with probes. Why?
Kubernetes starts new pods, waits for their readiness probes
(`/healthz`, `/api/tags`) to pass, THEN removes old pods. **Why add it:** zero
downtime and no "half-mixed" traffic; a failing new pod blocks the rollout
instead of taking the service down.

### Step 8 — Post-deploy health verification. Why?
Confirm the live URL answers: `GET /healthz` → ok, `/chat` and `/rag` return.
**Why add it:** green ICMP to a pod ≠ a working RAG chain; verify the contract.

### Step 9 — Rollback path. Why?
Because deployments fail, the pipeline must define how to revert: point back at
a previous image tag or previous commit. **Why add it:** a documented rollback
converts a potential outage into a minutes-long fix.

---

## What actually happened in *this* project (worked example)
1. We edited `rag/requirements.txt` (chromadb pin) and pushed.
2. Cloud Build rebuilt `genai/rag:1.0.0` for amd64 and pushed it.
3. `kubectl rollout restart deploy/rag-service` (imagePullPolicy:
   `Always`) made new pods pull the fresh tag.
4. Readiness probes confirmed the new pod healthy; old pod retired.
5. A manual ingest job re-indexed the docs with the new library.

That sequence — build → push → restart → probe → verify — is the CI/CD flow in
miniature, and each building block exists only because the previous one had a
specific GAP it filled.