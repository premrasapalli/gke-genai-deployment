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
