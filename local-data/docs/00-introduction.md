# GKE GenAI Deployment — Introduction & Overview

This project is an end-to-end Generative AI (GenAI) platform that runs on Google
Kubernetes Engine (GKE). It lets you chat with a Large Language Model (LLM),
ask questions grounded in your own documents, and manage the whole thing with
version-controlled infrastructure and code.

Think of it as a "self-hosted AI assistant" — no calls to closed APIs, no keys
for an external provider. Instead, everything runs inside your own cloud
cluster using open-source tools.

## The four big building blocks

1. **Model serving** — hosts the AI models that generate text. We use vLLM (or
   the lighter Ollama in CPU mode) to run the LLM, and a second service called
   "Text Embeddings Inference" (TEI) to turn text into numbers (embeddings).

2. **RAG (Retrieval Augmented Generation)** — lets the model answer questions
   using *your* documents instead of only its own training data. Documents are
   split into chunks, converted to embeddings, and stored in a vector database
   (Chroma). At question time, relevant chunks are retrieved and given to the
   LLM as context.

3. **API Gateway** — a FastAPI application that exposes simple HTTP endpoints
   (`/chat`, `/rag`, `/models`, `/healthz`) so a frontend or a script can talk
   to the AI without knowing about any of the internals.

4. **Infrastructure as Code** — everything (cluster, storage, node pools) is
   defined in Terraform and deployed with Kubernetes manifests, so the whole
   platform is reproducible, reviewable, and GitOps-ready.

## Quick reference

### Model Serving

The project serves LLMs using **vLLM**, an OpenAI-compatible inference server.
Models are pulled into a shared model volume and served on port 8000 with a
`/v1` OpenAI-compatible API. A lightweight alternative, **Ollama**, is provided
for local or low-resource runs on port 11434.

### RAG Pipeline

RAG (Retrieval Augmented Generation) improves LLM answers by retrieving
relevant context before generation. This project indexes documents into a
**Chroma** vector database. Ingestion loads markdown and text files, splits them
into chunks, and stores embeddings. At query time, the retriever performs a
similarity search and passes the top-k chunks into the prompt as context.

### API Gateway

A FastAPI gateway is the single front door of the platform. It exposes:

| Endpoint | Method | What it does                                            |
| -------- | ------ | ------------------------------------------------------- |
| `/healthz` | GET | Liveness check; returns `{"status":"ok"}`.            |
| `/models`  | GET | Reports which LLM is being served (e.g. `qwen2.5:0.5b`). |
| `/chat`    | POST | Sends a prompt to the LLM and returns the plain chat answer. |
| `/rag`     | POST | Retrieves relevant document chunks from Chroma, then generates a grounded answer. |

Example chat call: `POST /chat` with `{"prompt": "What is a token?"}` returns
`{"answer": "..."}`. Example RAG call: `POST /rag` with
`{"query": "How are models served?"}` returns an answer grounded in this
knowledge base.

### Infrastructure

Terraform provisions a GKE cluster and Artifact Registry on GCP. Deployments
are Kubernetes manifests ready for GitOps with ArgoCD.

### Embeddings

Embeddings are produced from an OpenAI-compatible embedding endpoint on port
8001. Use the same embedding model at ingestion and query time.

## Who is this for?

Anyone who wants to learn how modern AI applications are actually deployed in
production: an LLM server, a retrieval pipeline, an API layer, and the cloud
plumbing that keeps them running. The rest of this knowledge base explains each
piece in depth.
