# Troubleshooting Playbook: the Real Issues We Hit

This chapter documents, with real error messages and the actual fixes, every
class of problem a beginner will run into. It is a condensed war story of this
project.

## 1. GPU pool stuck in "PROVISIONING" forever

Symptom: the gpu-pool never becomes RUNNING; condition keeps failing.

```text
Quota 'GPUS_ALL_REGIONS' exceeded.  Limit: 0.0 globally.
```

The L4 quota is enforced **globally**, not per region: the global quota
`GPUS_ALL_REGIONS` was 0, so even though a regional `NVIDIA_L4_GPUS` quota
seemed to allow 1 GPU, the node pool could never schedule. Even deleting and
recreating the pool in another zone did not help, because the problem is the
global quota, not the zone.

Fix: leave the GPU path off (`enable_gpu_pool = false`) and run on CPU, or
request a `GPUS_ALL_REGIONS` quota increase in
Google Cloud Console → IAM & Admin → Quotas.

## 2. Billing disabled → nothing works in GCP

Symptom: various "permission" or "billing" errors across the project.

```bash
gcloud billing projects link aiml-project-idp --billing-account=01716C-ECBC7F-34FFF7
```

Verify with `gcloud billing projects describe aiml-project-idp` → it should
report `billingEnabled: true`.

## 3. "exec format error" after a local image build

Symptom: pods crash-loop with `standard_init_linux.go:... exec format error`.

Cause: the image was built on a Mac (arm64) but the GKE nodes are x86.

Fix: build for `linux/amd64`. This repo delegates image building to Cloud
Build (x86 hosts) via `cloudbuild.yaml`, which guarantees amd64 images.

## 4. `No module named 'app'` in the gateway

Cause: the Dockerfile copied the app directory flat:

```dockerfile
# broken
COPY app ./          # puts app/* at container root
# works
COPY app/ ./app/     # keeps the package at /app so `import app` resolves
```

Fix the COPY source/target and rebuild.

## 5. RAG says "Ingested N chunks" but the query finds nothing

Symptom: the ingest job logs `Ingested ... -> 4 chunks`, but every `/rag`
answer is generic (clearly not grounded), and the query service reports
count 0, with no `chroma.sqlite3` next to `/data/chroma`.

Root cause: `langchain-chroma==0.1.4` silently **disables persistence** when
paired with `chromadb>=0.5`, running everything in-memory and discarding data
when the process exits. The add succeeded, but nothing was ever written to
disk.

Fix: pin the compatible pairing. This repo uses `chromadb==0.4.24`. Rebuild
the rag image, delete the old manual ingest job, re-ingest, and confirm the
sqlite file now exists under `/data/chroma`.

## 6. Storage class "not found"

Symptom: a PVC stays `Pending` with `storageclasses.storage.k8s.io "pd-ssd"
not found`.

Fix: this cluster does not define `pd-ssd`; use a class that exists. `premium-rwo`
(pd-ssd-equivalent, zonal) for single-writer volumes and `nfs-filestore`
(Filestore CSI, regionally shared) for multi-writer volumes. Enable the CSI
driver for Filestore:

```bash
gcloud container clusters update genai-cluster --region=us-central1 \
  --update-addons=GcpFilestoreCsiDriver=ENABLED
```

Note the key is `GcpFilestoreCsiDriver`, not "FilestoreCSI".

## 7. `terraform` state lock "object doesn't exist"

Symptom: apply fails with `Error acquiring the state lock`, but
`force-unlock` reports the lock blob is gone.

Cause: the lock comes from an interrupted local `terraform apply` process that
is still holding the lock, or one that crashed leaving a stale blob.

Fix: find and kill the stuck process, then re-run `terraform apply`. If
`force-unlock` itself says the object is gone, the lock is already cleared.

## 8. A port-forward dies between commands

`kubectl port-forward` started "in the background" does not survive to the
next terminal command. Put the port-forward and the `curl` in the same
command:

```bash
kubectl port-forward -n genai svc/gateway 8080:80 >/dev/null & PF=$!
sleep 5
curl -s localhost:8080/healthz
kill $PF
```

## 9. Pod cannot pull from Artifact Registry

Fix the registry read with IAM:

```bash
gcloud artifacts repositories add-iam-policy-binding genai \
  --location=us-central1 \
  --member=serviceAccount:genai-gke@aiml-project-idp.iam.gserviceaccount.com \
  --role=roles/artifactregistry.reader
```

## Hygiene after any rebuild

1. `kubectl -n genai rollout restart deploy/gateway deploy/rag-service deploy/serving-llm deploy/serving-embedding`
2. Re-run the manual ingest job if RAG data was touched.
3. Confirm pods are `1/1 Running` and `/healthz` returns `{"status":"ok"}`.