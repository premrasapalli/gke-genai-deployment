# Document Ingestion: Chunking and Embedding

Before your documents can be searched, they must be loaded, split into small
pieces (chunks), and embedded. This is the **ingestion** phase.

## What the ingest job does

The `rag-ingest` Kubernetes CronJob runs the `python -m ingest --dir /data/docs`
command. Inside `rag/ingest.py` it:

1. **Finds all documents** with a supported extension under `/data/docs`
   (currently `.md` and `.txt`).
2. **Loads and chunks** each one using `rag/loader.py`.
3. **Embeds and stores** each chunk in Chroma via `store.add_documents(...)`.
4. **Logs** how many chunks were ingested.

## The seed step

Before ingestion, the job's `seed-docs` init container can copy documents from
a Google Cloud Storage (GCS) bucket into `/data/docs`. If `DOCS_GCS_URI` is
empty, it just uses whatever documents are already present in the shared volume
(for example, files you copied in with `kubectl cp`).

## Chunking, in short

Long documents are split into overlapping chunks (a few sentences each) because:

- The embedding model can only process a limited amount of text at once.
- Retrieval works best on short, focused pieces — a whole chapter is too broad
  to match a specific question.
- Chunks are then embedded and each becomes one row in the vector database.

## How to re-index after changing documents

Run a one-off job cloned from the scheduled CronJob:

```
kubectl create job --from=cronjob/rag-ingest rag-ingest-manual -n genai
```

Then confirm with:

```
kubectl get job -n genai rag-ingest-manual
kubectl logs -n genai job/rag-ingest-manual
```

The scheduled CronJob also re-runs ingestion every 6 hours automatically.
