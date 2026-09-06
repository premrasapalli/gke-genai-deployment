# GKE GenAI Deployment — Sample Knowledge Base

## Model Serving

The project serves LLMs using **vLLM**, an OpenAI-compatible inference server.
Models are pulled into a shared model volume and served on port 8000 with a
`/v1` OpenAI-compatible API. A lightweight alternative, **Ollama**, is provided
for local or low-resource runs on port 11434.

## RAG Pipeline

RAG (Retrieval Augmented Generation) improves LLM answers by retrieving
relevant context before generation. This project indexes documents into a
**Chroma** vector database. Ingestion loads markdown and text files, splits them
into chunks, and stores embeddings. At query time, the retriever performs a
similarity search and passes the top-k chunks into the prompt as context.

## API Gateway

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

## Infrastructure

Terraform provisions a GKE cluster and Artifact Registry on GCP. Deployments
are Kubernetes manifests ready for GitOps with ArgoCD.

## Embeddings

Embeddings are produced from an OpenAI-compatible embedding endpoint on port
8001. Use the same embedding model at ingestion and query time.
