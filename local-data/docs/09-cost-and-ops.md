# Cost Awareness & Everyday Operations

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
- The `cpu-pool` runs 3 x e2-standard-8 CPU nodes; on-demand pricing applies.
- GPU usage (if re-enabled later) is the largest variable cost.

Delete preview first: `terraform plan`, and always
`kubectl delete -k k8s/base` before `terraform destroy` to avoid orphaned
external resources such as the static IP.
