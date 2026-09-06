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
