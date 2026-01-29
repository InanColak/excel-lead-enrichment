FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

# Create data directories
RUN mkdir -p data/uploads data/output

EXPOSE 8002

CMD ["uvicorn", "lead_enrichment.api.server:app", "--host", "0.0.0.0", "--port", "8002"]
