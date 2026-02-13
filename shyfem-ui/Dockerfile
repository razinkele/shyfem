# SHYFEM UI Docker Image
# Multi-stage build for optimized image size

# Stage 1: Python dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and install Python packages
COPY pyproject.toml .
COPY shyfem_ui/__init__.py ./shyfem_ui/__init__.py
RUN pip install --no-cache-dir --user .

# Stage 2: Final image
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (OpenMP for SHYFEM)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -s /bin/bash appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY shyfem_ui/ ./shyfem_ui/
COPY pyproject.toml .

# Install the package (editable, uses already-installed deps)
RUN pip install --no-cache-dir -e .

# Create directories and set ownership
RUN mkdir -p /data/projects /data/db \
    && chown -R appuser:appuser /data /app

# Switch to non-root user
USER appuser

# Environment variables
ENV SHYFEM_UI_HOST=0.0.0.0
ENV SHYFEM_UI_PORT=8000
ENV SHYFEM_UI_DEPLOYMENT_MODE=server
ENV SHYFEM_UI_WORK_DIR=/data/projects
ENV SHYFEM_UI_DATABASE_URL=sqlite:////data/db/shyfem_ui.db
# Auth is strongly recommended for server deployments:
# ENV SHYFEM_UI_AUTH_ENABLED=true
# ENV SHYFEM_UI_AUTH_PASSWORD=changeme

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000')" || exit 1

# Run the application
CMD ["python", "-m", "shyfem_ui.app"]
