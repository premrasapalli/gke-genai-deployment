# LLM Fundamentals, Model Serving & Embeddings

This file covers the AI building blocks: what a language model is, how models
are served behind HTTP APIs, and how text is turned into vectors (embeddings).

---

# What Is a Large Language Model (LLM)?

A Large Language Model is a neural network trained on a massive amount of text
to predict the next word in a sentence. Given a prompt like "The capital of
France is", it continues: "...Paris." By repeating this one-step-ahead
prediction many times, it can write essays, answer questions, translate, and
summarize.

## Key ideas

- **Tokens** are the units the model reads and writes. A token is roughly a
  short piece of a word. For example, "hello world" might be split into
  "hello", " world". Models have a vocabulary of tens of thousands of tokens.

- **Context window** is the maximum number of tokens the model can consider at
  once. Everything the user types plus the model's reply must fit inside it.

- **Parameters** are the learned numbers inside the model. A "0.5B" model has
  0.5 billion parameters. Bigger models (7B, 70B) are smarter but need more
  memory and compute — usually a GPU.

- **Inference** is the act of running the model to produce a reply. This is
  what the *serving* services do.

## Why run your own model?

- **Privacy** — your prompts and documents never leave your infrastructure.
- **Cost control** — no per-token API fees at scale; you pay for the machines.
- **Customization** — choose any open model and swap it freely.

## The model used in the CPU demo

Because GPU quota is limited in this project, the CPU demo serves the small
model `qwen2.5:0.5b`. It has 0.5 billion parameters: fast to run on CPU, weak
reasoning, but perfect for learning and for testing the whole pipeline. When a
GPU becomes available, the same code serves a much larger model such as
`Qwen2.5-7B-Instruct`.

---

# Model Serving: vLLM and Ollama

"Model serving" means running a trained model behind an HTTP API so other
programs can call it. In this project there are two options.

## vLLM (GPU path)

vLLM is a high-performance inference server built for GPUs. It exposes an
**OpenAI-compatible API** at `/v1` on port 8000. That means a client designed
to talk to OpenAI's API can talk to our own vLLM by only changing the URL.

Example endpoint you can call:

```
POST /v1/chat/completions
```

with a JSON body containing messages, and the model name.

In this repository vLLM is configured (see `k8s/base/serving-llm.yaml` and the
GPU overlay) to load a model such as `Qwen/Qwen2.5-7B-Instruct` and serve it as
the model name `genai-model`.

## Ollama (CPU path)

On this project there is no GPU quota (the global GPU quota is zero), so vLLM
cannot run — its wheel requires a CUDA/GPU device. For the CPU-only bring-up we
instead use **Ollama**, a lightweight tool that runs LLMs on plain CPUs.

Ollama exposes an OpenAI-compatible API too, so the gateway and RAG service
talk to it exactly the same way. The CPU demo pulls `qwen2.5:0.5b` on startup
and serves it on port 8000.

## Why OpenAI-compatible matters

Every downstream component (the gateway, the RAG chain) uses the standard
OpenAI Python client. Because both vLLM and Ollama mimic that API, the
downstream code never changes regardless of which server is installed. This is
the "seam" that lets us swap serving backends easily.

---

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
