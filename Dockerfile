FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Create data directories (will be overridden by volume mount)
RUN mkdir -p data/uploads data/output

# Non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD ["uvicorn", "lead_enrichment.api.server:app", "--host", "0.0.0.0", "--port", "8002"]
