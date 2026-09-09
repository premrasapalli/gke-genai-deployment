# The RAG Pipeline — From Why to How

This file covers the complete RAG (Retrieval Augmented Generation) pipeline:
why it exists, how documents are ingested, how the vector database works, and
how grounded answers are generated.

---

# Why RAG Exists

Large Language Models are trained on data up to a cutoff date. They do not know
your private documents, your product's API, or your latest internal wiki. If
you ask about those topics, the model makes things up — a problem called a
**hallucination**.

## The clever fix: don't retrain, just tell the model

Retrieval Augmented Generation (RAG) does two things at question time:

1. **Retrieve** the most relevant snippets from your own document collection.
2. **Generate** the answer while the retrieved snippets are in the prompt.

So the model's answer is grounded in facts you gave it, instead of guessed from
its training data.

## The full RAG flow

```
Document ---> split into chunks ---> embed each chunk ---> store in Chroma
                                                              |
User question ---> embed the question ----------------------->|
                                                              |
         find the top-k closest chunks <-----------------------+
                                                              |
         prompt = "Context: <retrieved chunks> Question: <question>"
                                                              |
         LLM generates a grounded answer <-------------------+
```

## Two distinct phases

- **Ingestion** (offline): documents are chunked, embedded, and stored. Runs as
  a Kubernetes CronJob (`rag-ingest`) so it can re-run on a schedule.
- **Retrieval + generation** (online): the rag service handles each incoming
  question.

Because ingestion and querying are separate processes that share a database,
the storage must be shared and persistent — which is why the `rag-data` PVC
uses a FileStore volume that supports read-write-many access.

---

# Chroma Vector Database, Ingestion, and Retrieval

This section explains how the project actually stores and searches your
documents.

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

---

# Document Ingestion: Chunking and Embedding

Before your documents can be searched, they must be loaded, split into small
pieces (chunks), and embedded.

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

```bash
kubectl create job --from=cronjob/rag-ingest rag-ingest-manual -n genai
```

Then confirm with:

```bash
kubectl get job -n genai rag-ingest-manual
kubectl logs -n genai job/rag-ingest-manual
```

The scheduled CronJob also re-runs ingestion every 6 hours automatically.

---

# The RAG Answer Chain

Once documents are ingested, the online part of RAG answers questions. The
chain lives in `rag/chain.py` and is exposed by the rag service.

## Step by step: `rag_answer(query, k=4)`

1. **Retrieve context.** It calls `retrieve(query, k=4)`, which embeds the
   question and asks Chroma for the 4 closest chunks. `rag/retriever.py`
   wraps the store call and returns `(document, score)` pairs.

2. **Build a grounded prompt.** The code assembles a system instruction:

   > "You are a precise assistant. Answer ONLY from the provided context. If
   >   the context does not contain the answer, say you don't know. Cite the
   >   context section number."

   Then it places the retrieved chunks as `Context:` and the user's question as
   `Question:` in the user message.

3. **Generate with the LLM.** It sends this prompt to the serving LLM (Ollama
   in CPU mode, or vLLM in GPU mode) using the OpenAI client pointed at
   `LLM_BASE_URL`. The model replies with an answer constrained by the context.

## Why the system prompt matters

Because the model is told to answer *only from the context* and to say "I don't
know" otherwise, it is much less likely to hallucinate. This is the entire
point of RAG: keep the model honest by feeding it the facts.

## The model-name match requirement

The RAG chain calls the LLM with `model=LLM_MODEL`. This string **must match**
the served model name. With Ollama the model is `qwen2.5:0.5b`; with vLLM it is
`genai-model`. The gateway and rag service both set `LLM_MODEL` to match the
active backend, otherwise the LLM API returns an error.
