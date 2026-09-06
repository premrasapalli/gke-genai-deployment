# RAG, Part 2: Chroma Vector Database, Ingestion, and Retrieval

This document explains how the project actually stores and searches your
documents. Read `05-rag-overview.md` first for the "why".

## The pieces

- **Source docs** live in the `rag-data` volume under `/data/docs`. The ingest
  job reads every `.md` and `.txt` file there.
- **Chroma** is the vector database. It holds, for each document chunk, the
  text plus its embedding vector. Data is persisted to disk under
  `/data/chroma` (configured through the `RAG_PERSIST_DIR` environment
  variable).
- **The collection** is Chroma's term for a named set of vectors. Both the
  ingest job and the query service use the collection `knowledge_base`
  (`RAG_COLLECTION`), so ingested data is literally the same store that is
  searched at query time.

```
documents ──► split into chunks ──► embed (TEI) ──► upsert into Chroma
                                                          │
query ──► embed (TEI) ──► similarity search (top-k) ◄────┘
             │
             └──► context → prompt → LLM → grounded answer
```

## Ingestion (`python -m ingest --dir /data/docs`)

1. Walks `/data/docs` for files ending in `.md` or `.txt`.
2. Loads each file and splits it into overlapping chunks.
3. Emits embeddings for every chunk by calling TEI (`POST /embeddings`).
4. Upserts chunk text + embedding into Chroma with stable ids like
   `intro-0`, `intro-1`.

Run it manually, on demand, with:

```bash
kubectl create job --from=cronjob/rag-ingest rag-ingest-manual -n genai
kubectl logs -n genai job/rag-ingest-manual --tail=20
```

A CronJob (`rag-ingest`) re-runs the same ingestion every 6 hours.

## Retrieval (`rag/retriever.py`)

At question time the service:

1. Embeds your question with the **same embedding model** used at ingestion
   (this consistency is critical — a different model would produce unrelated
   vectors).
2. Runs a similarity search and returns the `k` most similar chunks (default
   `k=4`), each with a score.
3. Sends those chunks as "Context" in the prompt, with a system instruction
   telling the model to answer only from that context.

## An important gotcha (fixed)

`langchain-chroma` silently falls back to an **in-memory**, non-persistent
store when it is paired with an incompatible `chromadb` version. Symptoms:
ingestion logs "Ingested ... N chunks", but the query service finds zero
results and no `/data/chroma/chroma.sqlite3` file ever appears.

This project pins `chromadb==0.4.24`, which is the version `langchain-chroma`
0.1.4 supports for true on-disk persistence. If you upgrade either library,
verify persistence by checking that `chroma.sqlite3` exists under
`/data/chroma` after an ingest run.

## Verifying the store

Exec into the running service and inspect the collection:

```bash
R=$(kubectl get pod -n genai -l app=rag-service -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n genai "$R" -- python -c \
  "from config import get_store; s=get_store(); print('count:', s._collection.count())"
```

A count greater than zero means retrieval has data to find.