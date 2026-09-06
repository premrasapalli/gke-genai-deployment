# End-to-End Example: From an Empty Project to a Grounded RAG Demo

This is the fastest path for a student to see the whole system work. Read the
numbered chapters in order (`01` → `09`) for the theory; this chapter is the
practical runbook.

## 0. Prerequisites (once)

- `gcloud` logged in and billing linked on the project.
- `kubectl` configured for the cluster:
  ```bash
  gcloud container clusters get-credentials genai-cluster --region=us-central1 --project=aiml-project-idp
  ```

## 1. Build and deploy the app

From the repository root:

```bash
gcloud builds submit --region=us-central1 --config=cloudbuild.yaml .
kubectl apply -k k8s/base
kubectl -n genai wait --for=condition=ready pod -l app=serving-llm --timeout=300s
kubectl -n genai get pods
```

Wait until all five workload pods report `1/1 Running`:

```
gateway-xxxxxxxxxx-ccccc            2/2     Running
rag-service-xxxxxxxxxx-ccccc        1/1     Running
serving-llm-xxxxxxxxxx-ccccc        1/1     Running
serving-embedding-xxxxxxxxxx-ccccc  1/1     Running
```

(The gateway may have two replicas.)

## 2. Check the health of the stack

```bash
kubectl port-forward -n genai svc/gateway 8080:80 >/dev/null & PF=$!
sleep 5
curl -s localhost:8080/healthz      # -> {"status":"ok"}
curl -s localhost:8080/models       # -> qwen2.5:0.5b
kill $PF
```

## 3. Seed documents and ingest

Docs live in the shared `rag-data` volume at `/data/docs`. Copy the knowledge
base into it from your laptop:

```bash
R=$(kubectl get pod -n genai -l app=rag-service -o jsonpath='{.items[0].metadata.name}')
kubectl cp local-data/docs/intro.md genai/$R:/data/docs/
```

Then run the ingestion job once:

```bash
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

You should see a non-zero count and a `chroma.sqlite3` file. If the count is 0,
see `12-troubleshooting.md` issue 5.

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
A vague, generic answer means retrieval returned nothing: re-check the count
and the persistence note in `06-rag-deep-dive.md`.

## Everyday ops cheat-sheet

| Task                         | Command                                                       |
| ---------------------------- | ------------------------------------------------------------- |
| Watch the workloads          | `kubectl -n genai get pods -w`                                |
| Tail the gateway logs        | `kubectl -n genai logs deploy/gateway -f`                     |
| Re-ingest the knowledge base | `kubectl create job --from=cronjob/rag-ingest rag-ingest-manual -n genai` |
| Restart after image rebuild  | `kubectl -n genai rollout restart deploy/gateway deploy/rag-service deploy/serving-llm deploy/serving-embedding` |
| See the ingress address      | `gcloud compute addresses describe gateway-static --region=us-central1 --format='value(address)'` |
| Tear down the app            | `kubectl delete -k k8s/base`                                  |
| Tear down the cluster        | `terraform destroy` (data volumes persist until deleted)      |

## Cost awareness

- The Filestore `rag-data` volume is billed at a 1 TiB minimum even though the
  PVC asks for 100 GiB — it is the biggest fixed cost (~$170/month class).
- The `cpu-pool` runs 3 × e2-standard-8 CPU nodes; on-demand pricing applies.
- GPU usage (if re-enabled later) is the largest variable cost.

Delete preview first: `terraform plan`, and always
`kubectl delete -k k8s/base` before `terraform destroy` to avoid orphaned
external resources such as the static IP.