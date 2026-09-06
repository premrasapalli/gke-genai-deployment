# Embeddings and Text Embeddings Inference (TEI)

An **embedding** is a list of numbers (a vector) that captures the *meaning* of
a piece of text. The key property: texts with similar meaning have similar
vectors, so we can compare meanings by computing vector distance.

Example: "How do I reset my password?" and "I forgot my login" produce vectors
that are close together, even though they share almost no words.

## What is an embedding model?

It is a model trained specifically to output these meaning-vectors. We use the
open model `BAAI/bge-small-en-v1.5`. It is small, fast, and works well on CPU.

## How TEI serves embeddings

**Text Embeddings Inference (TEI)** is a server that exposes a simple HTTP API
to turn text into embeddings:

```
POST /embeddings
{"model": "BAAI/bge-small-en-v1.5", "input": "some text"}
```

In GKE, TEI runs as the `serving-embedding` deployment on port 8001. Because it
is OpenAI-compatible, our RAG code calls it through the standard OpenAI client.

## Where embeddings are used

Embeddings are the heart of RAG:

- **At ingest time**, every document chunk is converted to an embedding and
  stored in the vector database.
- **At query time**, the user's question is converted to an embedding, and the
  database finds the stored chunk-vectors closest to it.

Crucially, the **same embedding model must be used** at ingest and query time.
If they differ, the vectors live in different "meaning spaces" and retrieval
fails. We keep them consistent with the `EMBEDDING_MODEL` setting shared by
both the ingest job and the rag service.
