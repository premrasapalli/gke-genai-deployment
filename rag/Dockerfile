# RAG pipeline image: ingestion worker + retrieval service.
FROM python:3.12-slim

WORKDIR /rag

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default runs the ingestion job; use `python -m service` for the HTTP service.
CMD ["python", "-m", "ingest", "--dir", "/data/docs"]