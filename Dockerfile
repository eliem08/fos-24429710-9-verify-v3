# Dockerfile for InvoiceLedger
FROM python:3.11-slim

# Install system dependencies: PostgreSQL client libs and PDF utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pinned Python dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create storage directories
RUN mkdir -p /app/archive /app/downloaded_invoices /app/uploads /app/sample_invoices

EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0
ENV WEB_CONCURRENCY=1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
