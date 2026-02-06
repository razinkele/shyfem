# SHYFEM UI Docker Image
# Multi-stage build for optimized image size

# Stage 1: Python dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Final image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY shyfem_ui/ ./shyfem_ui/
COPY pyproject.toml .

# Install the package
RUN pip install --no-cache-dir -e .

# Create directories
RUN mkdir -p /data/projects /data/db

# Environment variables
ENV SHYFEM_UI_HOST=0.0.0.0
ENV SHYFEM_UI_PORT=8000
ENV SHYFEM_UI_DEPLOYMENT_MODE=server
ENV SHYFEM_UI_WORK_DIR=/data/projects
ENV SHYFEM_UI_DATABASE_URL=sqlite:////data/db/shyfem_ui.db

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000')" || exit 1

# Run the application
CMD ["python", "-m", "shyfem_ui.app"]
