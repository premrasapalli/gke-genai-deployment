# Retrieval Augmented Generation (RAG), Part 1: Why It Exists

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

The next file explains the vector database and similarity search in detail.
