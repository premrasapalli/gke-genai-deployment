# The API Gateway

The **API gateway** is a FastAPI application (a Python web framework) that is
the single entry point into the whole AI system. It lives in the `gateway/`
directory and runs as the `gateway` Kubernetes deployment.

## Why have a gateway at all?

The internals — the LLM server, the embedding server, the RAG service — each
have their own addresses and details. A frontend or a CLI should not need to
know about any of them. The gateway gives clients:

- **One stable URL and port** (port 80 via the `gateway` Service).
- **Simple, stable endpoints.**
- **Optional API-key authentication.**

It also hides which model server is installed underneath (Ollama vs vLLM).

## The endpoints

- `POST /chat` — a plain chat with the LLM. You send messages; it streams/returns
  the model's reply.
- `POST /rag` — ask a question grounded in your documents. The gateway forwards
  to the rag service, which does retrieval and generation.
- `GET /models` — lists the models the serving backend currently has loaded.
- `GET /healthz` — readiness/health check used by Kubernetes probes.

## How the gateway talks to everything

The gateway is configured entirely with environment variables:

- `LLM_URL` — where the LLM lives (defaults to `http://serving-llm:8000/v1`).
- `LLM_MODEL` — the served model name (e.g. `qwen2.5:0.5b` or `genai-model`).
- `RAG_URL` — the rag service (defaults to `http://rag-service:8080`).
- `API_KEY` — optional shared secret for `X-API-Key` header auth.

Because these are just values in the Kubernetes manifest, pointing the whole
system at a different model or backend is a config change, not a code change.
