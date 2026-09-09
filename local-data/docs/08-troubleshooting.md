# Troubleshooting — Every Failure We Hit and Why

This is the complete runbook of every obstacle between "nothing exists" and the
live public URL, with real error messages, root causes, and fixes.

## 1. GPU pool stuck in "PROVISIONING" forever

Symptom: the gpu-pool never becomes RUNNING; condition keeps failing.

```text
Quota 'GPUS_ALL_REGIONS' exceeded.  Limit: 0.0 globally.
```

The L4 quota is enforced **globally**, not per region: the global quota
`GPUS_ALL_REGIONS` was 0, so even though a regional `NVIDIA_L4_GPUS` quota
seemed to allow 1 GPU, the node pool could never schedule.

Fix: leave the GPU path off (`enable_gpu_pool = false`) and run on CPU, or
request a `GPUS_ALL_REGIONS` quota increase in Google Cloud Console -> IAM &
Admin -> Quotas.

## 2. Billing disabled -> nothing works in GCP

Symptom: various "permission" or "billing" errors across the project.

```bash
gcloud billing projects link aiml-project-idp --billing-account=01716C-ECBC7F-34FFF7
```

Verify with `gcloud billing projects describe aiml-project-idp` -> it should
report `billingEnabled: true`.

## 3. Terraform apply hung; state locked

Symptom: lock error `Error acquiring the state lock`, but `force-unlock`
reports the lock blob is gone.

Cause: an earlier apply process died while holding the lock, and a known stale
PID lingered.

Fix: `kill <pid>` then `terraform force-unlock <lock-id>`. If `force-unlock`
itself says the object is gone, the lock is already cleared.

## 4. Drift — cpu-pool RUNNING, gpu-pool ERROR, state inconsistent

Symptom: Terraform state said gpu-pool existed but Cloud showed ERROR/lost.

Fix: refresh, adjust `node_locations` to an L4 zone, delete the errored pool
through GKE directly, re-apply CPU-only.

Why: keep Terraform state and reality aligned; a stale state entry poisons
every later plan.

## 5. "exec format error" after a local image build

Symptom: pods crash-loop with `standard_init_linux.go:... exec format error`.

Cause: the image was built on a Mac (arm64) but the GKE nodes are x86.

Fix: build for `linux/amd64`. This repo delegates image building to Cloud
Build (x86 hosts) via `cloudbuild.yaml`, which guarantees amd64 images.

## 6. ImagePullBackOff / `docker.io/genai/...` not found

Symptom: pods pull `docker.io/genai/gateway:1.0.0` and fail.

Root cause: base manifests carry short names (`genai/gateway`); applying
`k8s/base` (instead of the overlay) skips the registry rewrite.

Fix: `kubectl apply -k k8s/overlays/prod` (overlay rewrites names to
`us-central1-docker.pkg.dev/aiml-project-idp/genai/...`).

## 7. `No module named 'app'` in the gateway

Cause: the Dockerfile copied the app directory flat:

```dockerfile
# broken
COPY app ./          # puts app/* at container root
# works
COPY app/ ./app/     # keeps the package at /app so `import app` resolves
```

Fix the COPY source/target and rebuild.

## 8. vLLM has no CPU wheel

Symptom: vLLM exits `Failed to infer device type` on CPU nodes.

Fix: use Ollama (`ollama/ollama:latest`, model `qwen2.5:0.5b`) on CPU nodes;
vLLM reserved for GPU nodes.

Why: pip vLLM requires CUDA for a serving wheel; Ollama is a prebuilt
CPU-capable runtime for small models.

## 9. Language model download fails in the pod

Symptom: init/download step fails, `PermissionError` on `/models` or HF
"relative URL without a base" errors.

Fixes:
- add `fsGroup: 1001` + `fsGroupChangePolicy: Always` to the pod spec so the
  mount is writable by the runtime user;
- set `HF_HUB_DISABLE_XET=1` to avoid the Xet download path;
- preload models via the `model-loader` initContainer into a dedicated PVC,
  and point TEI at the local path instead of downloading on boot.

## 10. RAG says "Ingested N chunks" but the query finds nothing (the big one)

Symptom: the ingest job logs `Ingested ... -> 4 chunks`, but every `/rag`
answer is generic (clearly not grounded), and the query service reports
count 0, with no `chroma.sqlite3` next to `/data/chroma`.

Root cause: `langchain-chroma==0.1.4` silently **disables persistence** when
paired with `chromadb>=0.5`, running everything in-memory and discarding data
when the process exits.

Fix: pin the compatible pairing. This repo uses `chromadb==0.4.24`. Rebuild
the rag image, delete the old manual ingest job, re-ingest, and confirm the
sqlite file now exists under `/data/chroma`.

Verify: in the rag pod, `chromadb.PersistentClient(path="/data/chroma")
.get_collection("knowledge_base").count()` must be 122 (or your chunk count).

## 11. `kubectl cp` into a pod keeps failing (`pods ... not found`)

Symptom: copy races: pod name resolves, then the pod is replaced.

Fix: don't copy into a pod; use the GCS seed path (`DOCS_GCS_URI`) and run
the ingest job, which writes the PVC directly.

Why: pods are ephemeral (deployments roll), but the PVC survives; the job
is decoupled from pod identity.

## 12. Browser root path gives `{"detail":"Not Found"}`

Symptom: opening `/` returns a FastAPI 404.

Fix: added an HTML playground at `/` (chat + RAG tabs); endpoints were
always only `/healthz`, `/chat`, `/rag`, `/models`.

## 13. Storage class "not found"

Symptom: a PVC stays `Pending` with `storageclasses.storage.k8s.io "pd-ssd"
not found`.

Fix: this cluster does not define `pd-ssd`; use a class that exists.
`premium-rwo` (pd-ssd-equivalent, zonal) for single-writer volumes and
`nfs-filestore` (Filestore CSI, regionally shared) for multi-writer volumes.

```bash
gcloud container clusters update genai-cluster --region=us-central1 \
  --update-addons=GcpFilestoreCsiDriver=ENABLED
```

## 14. GCE Ingress never gets an address

Symptom: `genai-gateway` ingress shows no `ADDRESS` for hours; no forwarding
rules are created by the ingress controller.

Workaround: expose a `type: LoadBalancer` service (`gateway-lb`) which got IP
`34.63.204.167` with all nodes HEALTHY.

## 15. NodePort URL unreachable

Symptom: `http://<node-ip>:30080/healthz` times out.

Fix: added firewall rule `genai-gateway-nodeport` opening tcp:30080.

Why: GKE's default firewall doesn't expose arbitrary nodePorts to the
internet; the LB service sidesteps this entirely.

## 16. A port-forward dies between commands

`kubectl port-forward` started "in the background" does not survive to the
next terminal command. Put the port-forward and the `curl` in the same
command:

```bash
kubectl port-forward -n genai svc/gateway 8080:80 >/dev/null & PF=$!
sleep 5
curl -s localhost:8080/healthz
kill $PF
```

---

## General debugging kit

- `kubectl -n genai describe pod <pod>` — events tell you the pull/start error.
- `kubectl -n genai get events --sort-by=.lastTimestamp` — recent cluster events.
- `kubectl -n genai logs deploy/<svc>` for app logs; check the ingest job logs
  for "Total chunks".
- `gcloud builds list` — did the image actually build/push?
- `gcloud compute target-pools get-health <pool> --region=us-central1` — LB
  node health.

## Hygiene after any rebuild

1. `kubectl -n genai rollout restart deploy/gateway deploy/rag-service deploy/serving-llm deploy/serving-embedding`
2. Re-run the manual ingest job if RAG data was touched.
3. Confirm pods are `1/1 Running` and `/healthz` returns `{"status":"ok"}`.

Each failure above taught a lesson that became a guardrail: quotas before GPUs,
overlay before volume, amd64 before build, chromadb pin before RAG, LB before
marketing the URL.
