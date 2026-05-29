# URAAS Production Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create app user
RUN useradd -m -u 1000 uraas && \
    mkdir -p /app /app/storage/pdfs /app/data /app/logs && \
    chown -R uraas:uraas /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local /usr/local

# Copy application code
COPY --chown=uraas:uraas . .

# Switch to app user
USER uraas

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/api/analytics/overview', timeout=5)"

# Run database initialization and then start gunicorn
CMD python scripts/init_db.py && gunicorn --bind 0.0.0.0:8080 --workers 4 --worker-class gevent --worker-connections 1000 --timeout 120 --access-logfile - --error-logfile - --log-level info uraas.dashboard.app:app
