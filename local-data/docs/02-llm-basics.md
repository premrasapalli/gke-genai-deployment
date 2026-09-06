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
