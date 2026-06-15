# URAAS Production Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the spaCy model into the builder image so it's baked in.
# This avoids the fragile GitHub URL in requirements.txt and ensures the model
# is available offline inside the container without fetching at runtime.
RUN python -m spacy download en_core_web_sm

# Stage 2: Runtime
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default to production safety; can be overridden for local dev.
    URAAS_ENV=production

# Create non-root app user
RUN useradd -m -u 1000 uraas && \
    mkdir -p /app /app/storage/pdfs /app/data /app/logs && \
    chown -R uraas:uraas /app

# Install runtime system dependencies.
# curl is required for the HEALTHCHECK command.
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python packages + spaCy model from builder
COPY --from=builder /usr/local /usr/local

# Copy application code (owned by app user)
COPY --chown=uraas:uraas . .

USER uraas

EXPOSE 8080

# Health check — uses the public /health endpoint (no auth required).
# /api/analytics/overview requires a login session and always returns 401 unauthenticated.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run database initialization and then start gunicorn using the config file.
# gunicorn_config.py sets gthread workers to match SocketIO async_mode="threading".
CMD python scripts/init_db.py && gunicorn --config gunicorn_config.py uraas.dashboard.app:app
