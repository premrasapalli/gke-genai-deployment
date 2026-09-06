# Troubleshooting — From Start to Live (Every Failure We Hit and Why)

This is the complete runbook of every obstacle between "nothing exists" and the
live public URL, with the **why each fix works** next to it. If something breaks
again, check here first.

## 1. GPUs unavailable / quota 0 — "GPUS_ALL_REGIONS exceeded 0.0"
- **Symptom:** `gpu-pool` kept provisioning an ERROR node pool.
- **Root cause:** project global GPU quota `GPUS_ALL_REGIONS = 0` (L4 GPUs also
  limited to us-central1-a/b/c).
- **Fix:** CPU-only now (`enable_gpu_pool=false`), file a quota request.
- **Why this fixes it:** you can't create what quota forbids; CPU mode uses
  only always-available e2 VMs.

## 2. `terraform apply` hung; state locked
- **Symptom:** lock error `Error acquiring the state lock`.
- **Root cause:** an earlier apply process died while holding the lock, and a
  known stale PID (37827) lingered.
- **Fix:** `kill <pid>` then `terraform force-unlock <lock-id>`.
- **Why:** the lock exists so two applies don't race; when the owner is dead,
  forcing unlock is safe.

## 3. Billing disabled in the project
- **Symptom:** various "disabled" / quota errors when creating resources.
- **Fix:** `gcloud billing projects link aiml-project-idp --billing-account=01716C-ECBC7F-34FFF7`.
- **Why:** no billing ⇒ GCP rejects almost any mutating operation; linking
  resolves the whole class of mystery errors at once.

## 4. Drift — cpu-pool RUNNING, gpu-pool ERROR, state inconsistent
- **Symptom:** Terraform state said gpu-pool existed but Cloud showed ERROR/lost.
- **Fix:** refresh, adjust `node_locations` to an L4 zone, delete the errored
  pool through GKE directly, re-apply CPU-only.
- **Why:** keep Terraform state and reality aligned; a stale state entry poisons
  every later plan.

## 5. **ImagePullBackOff / `docker.io/genai/...` not found**
- **Symptom:** pods pull `docker.io/genai/gateway:1.0.0` and fail.
- **Root cause:** base manifests carry short names (`genai/gateway`); applying
  `k8s/base` (instead of the overlay) skips the registry rewrite.
- **Fix:** `kubectl apply -k k8s/overlays/prod` (overlay rewrites names to
  `us-central1-docker.pkg.dev/aiml-project-idp/genai/...`).
- **Why:** the overlay's `images:` transformer injects the full registry path;
  without it Kubernetes treats `genai/gateway` as a Docker Hub image.

## 6. `exec format error` / `Failed to infer device type`
- **Symptom:** amd64 cluster nodes reject arm64 images built on a Mac.
- **Root cause:** `docker build` locally on Apple Silicon produces `arm64`.
- **Fix:** build via Cloud Build (x86 runners), i.e.
  `gcloud builds submit --config=cloudbuild.yaml .`; for local builds use
  `--platform linux/amd64`.
- **Why:** the descriptor architecture must match the node CPU exactly.

## 7. vLLM has no CPU wheel
- **Symptom:** vLLM exits `Failed to infer device type` on CPU nodes.
- **Fix:** use Ollama (`ollama/ollama:latest`, model `qwen2.5:0.5b`) on CPU
  nodes; vLLM reserved for GPU nodes.
- **Why:** pip vLLM requires CUDA for a serving wheel; Ollama is a prebuilt
  CPU-capable runtime for small models.

## 8. Language model download fails in the pod
- **Symptom:** init/download step fails, `PermissionError` on `/models` or HF
  "relative URL without a base" errors.
- **Fixes:**
  - add `fsGroup: 1001` + `fsGroupChangePolicy: Always` to the pod spec so the
    mount is writable by the runtime user;
  - set `HF_HUB_DISABLE_XET=1` to avoid the Xet download path;
  - preload models via the `model-loader` initContainer into a dedicated PVC,
    and point TEI at the local path instead of downloading on boot.
- **Why each works:** fsGroup fixes ownership; XET disables a flaky transport;
  preloading removes the network dependency from readiness.

## 9. **RAG answers generically instead of using your docs (the big one)**
- **Symptom:** `/rag` returns plausible text but never quotes your documents;
  ingest logs "Ingested … chunks" yet queries find nothing.
- **Root cause:** `langchain-chroma 0.1.4` + `chromadb 0.5.x` silently falls back
  to an **in-memory** store. `get_store()` never writes
  `/data/chroma/chroma.sqlite3`; every pod restart wipes the index.
- **Fix:** pin `chromadb==0.4.24` (the version langchain-chroma 0.1.4
  persists with), rebuild, redeploy, re-ingest.
- **Why:** chromadb 0.5 dropped the API langchain-chroma 0.1.4 expects for
  on-disk persistence; the pin restores true SQLite persistence.
- **Verify:** in the rag pod, `chromadb.PersistentClient(path="/data/chroma")
  .get_collection("knowledge_base").count()` must be 122 (or your chunk count).

## 10. `kubectl cp` into a pod keeps failing (`pods ... not found`)
- **Symptom:** copy races: pod name resolves, then the pod is replaced.
- **Fix:** don't copy into a pod; use the GCS seed path (`DOCS_GCS_URI`) and run
  the ingest job, which writes the PVC directly.
- **Why:** pods are ephemeral (deployments roll), but the PVC survives; the job
  is decoupled from pod identity.

## 11. Browser root path gives `{"detail":"Not Found"}`
- **Symptom:** opening `/` returns a FastAPI 404.
- **Fix:** added an HTML playground at `/` (chat + RAG tabs); endpoints were
  always only `/healthz`, `/chat`, `/rag`, `/models`.
- **Why:** a user-facing system needs a human page, not a JSON 404.

## 12. GCE Ingress never gets an address
- **Symptom:** `genai-gateway` ingress shows no `ADDRESS` for hours; no
  forwarding rules are created by the ingress controller.
- **Workaround used:** expose a `type: LoadBalancer` service
  (`gateway-lb`) → got IP `34.63.204.167` with all nodes HEALTHY.
- **Why:** the LB Service path is handled by cloud provider tooling that works,
  while the GCE ingress controller is what's stuck. (Fix the ingress separately
  if you need the reserved global IP.)

## 13. NodePort URL unreachable
- **Symptom:** `http://<node-ip>:30080/healthz` times out.
- **Fix:** added firewall rule `genai-gateway-nodeport` opening tcp:30080.
- **Why:** GKE's default firewall doesn't expose arbitrary nodePorts to the
  internet; the LB service sidesteps this entirely.

## General debugging kit
- `kubectl -n genai describe pod <pod>` — events tell you the pull/start error.
- `kubectl -n genai get events --sort-by=.lastTimestamp` — recent cluster events.
- `kubectl -n genai logs deploy/<svc>` for app logs; check the ingest job logs
  for "Total chunks".
- `gcloud builds list` — did the image actually build/push?
- `gcloud compute target-pools get-health <pool> --region=us-central1` — LB
  node health.

Each failure above taught a lesson that became a guardrail: quotas before GPUs,
overlay before volume, amd64 before build, chromadb pin before RAG, LB before
marketing the URL.