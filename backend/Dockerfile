FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PostgreSQL, PDF processing, and other utilities
# This fixes the psycopg/libpq issue by installing libpq-dev
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    curl \
    poppler-utils \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
