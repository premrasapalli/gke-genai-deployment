# CI/CD: How Changes Reach the Running Platform

CI/CD stands for **Continuous Integration** and **Continuous Deployment**. It is
the automated pipeline that takes a code change, tests it, builds it, ships it,
and puts it live — with as little human clicking as possible. This knowledge
base explains the project's pipeline end to end, including what happens in the
background at each step.

## The high-level idea

```
You push code (git) -> CI builds & tests -> images pushed to Artifact Registry
   -> CD deploys new k8s manifests -> cluster rolls out updates
```

Everything is driven by **GitHub Actions** (the CI part) plus either **kubectl**
or **ArgoCD** (the CD part). Git is the single source of truth: whatever is in
the repository is what should be running.

## Step 1: Trigger — a push or pull request

When you push to the repository, GitHub Actions detects the event and starts a
workflow defined in `.github/workflows/build-push.yml`. In the background this
means GitHub spins up a fresh, isolated runner machine just for this run — so
the build always starts from a clean state.

## Step 2: Authenticate to Google Cloud (Workload Identity Federation)

Before the pipeline can push images, it must prove it is allowed to. The modern,
secure way is **Workload Identity Federation (WIF)**: GitHub exchanges a GitHub
token for a temporary Google Cloud credential. No long-lived secret keys are
ever stored in the repo. The workflow config provides:

- `PROJECT_ID` — `aiml-project-idp`
- `WIF_PROVIDER` — the identity provider resource
- `WIF_SERVICE_ACCOUNT` — the service account with permission to write images

## Step 3: Build the images

The pipeline builds the three first-party images:

- `genai/gateway` — the API gateway
- `genai/rag` — the RAG service and ingest job
- `genai/model-loader` — downloads models into the shared volume

It builds them for the **correct CPU architecture** (`linux/amd64`). This is
critical: if you build on an Apple Silicon laptop and forget `--platform
linux/amd64`, the image will not run on the cluster's amd64 nodes (you get the
famous `exec format error`). Building in the cloud pipeline avoids this problem
entirely because the build machine matches the target architecture.

## Step 4: Push to Artifact Registry

The built images are pushed to Google **Artifact Registry**:

```
us-central1-docker.pkg.dev/aiml-project-idp/genai/<name>:1.0.0
```

Images are **versioned** (e.g. `1.0.0`) rather than using `:latest`, because
versioned tags make builds reproducible and make rollbacks possible. Some
workflows also tag each push with a timestamp and commit SHA (e.g.
`1.0.<epoch>-<sha>`) so you can always tell exactly which commit produced an
image.

## Step 5: Deploy (the CD side)

Once images exist in Artifact Registry, the running cluster needs to start using
the new versions. There are two ways this project does it:

- **Manual kubectl** — run `kubectl apply -k k8s/overlays/prod` to apply the
  Kubernetes manifests. This is great for development and for a demo.
- **ArgoCD (GitOps)** — a controller inside the cluster continuously watches
  the git repo and automatically reconciles the cluster to match it. When your
  manifests change in git, ArgoCD applies them. This is "GitOps": the git repo,
  not a human, is the source of truth and the trigger for deployment.

## What happens in the background during a roll out

When new pod definitions reach the cluster, Kubernetes performs a **rolling
update**:

1. A new ReplicaSet is created with the new pod definition.
2. It starts a new pod with the new image.
3. Readiness probes (`/healthz`, `/api/tags`, etc.) are used to check the new
   pod is actually healthy.
4. Only then is an old pod terminated.

Because we set `imagePullPolicy: Always` on our app containers, each new pod
pulls the exact latest `1.0.0` tag rather than reusing a cached copy — so
re-pushed images are picked up automatically.

## What happens if something goes wrong

- If a new pod fails its readiness probe repeatedly, Kubernetes stops the
  rollout (it does not keep destroying healthy pods) and reports the pod state
  like `CrashLoopBackOff`.
- Because images and manifests are versioned and stored, you can roll back to a
  previous image tag or a previous git commit.
- Monitoring (see the `monitoring/` directory) raises alerts if a workload goes
  down or a node becomes unhealthy, so problems are caught automatically.

## Summary: the end-to-end life of a change

1. Developer edits code and commits.
2. GitHub Actions builds and pushes new `1.0.0` images (WIF auth, no secrets).
3. The change is merged and the manifests are applied (kubectl) — or ArgoCD
   auto-syncs from git.
4. Kubernetes rolls out new pods, verifying health with probes.
5. The gateway's `/healthz` reports the system is healthy; users call `/chat`
   and `/rag` as normal.
