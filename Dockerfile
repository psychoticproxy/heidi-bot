# Use Python 3.11 slim image for small size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (needed for asyncpg with PostgreSQL)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user for security
RUN useradd -m -r botuser && \
    chown -R botuser:botuser /app
USER botuser

# Health check (simple process check)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import psutil; exit(0 if 'python' in [p.name() for p in psutil.process_iter()] else 1)" || exit 1

# Start the bot
CMD ["python", "main.py"]

