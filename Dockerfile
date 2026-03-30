# ═══════════════════════════════════════════════════════════════════════════
# AUTO-REELS PRO v10.0 — PRODUCTION DOCKERFILE (Multi-stage)
# ═══════════════════════════════════════════════════════════════════════════

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY cloud/requirements.txt .

# Create wheels (faster installation in final stage)
RUN pip install --user --no-cache-dir wheel
RUN pip wheel --user --no-cache-dir --requirement requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Create non-root user for security
RUN groupadd -r autoreels && useradd -r -g autoreels autoreels

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1-mesa-glx \
    postgresql-client \
    redis-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /root/.local /home/autoreels/.local

# Set environment for Python
ENV PATH=/home/autoreels/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Install requirements
RUN pip install --user --no-index --find-links /home/autoreels/.local -r requirements.txt 2>/dev/null || true

# Copy application code
COPY cloud/ /app/cloud/
COPY cloud/src/ /app/cloud/src/

# Create required directories
RUN mkdir -p /app/cloud/logs /app/cloud/queue /app/cloud/config \
    && chown -R autoreels:autoreels /app

# Switch to non-root user
USER autoreels

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command (web API)
CMD ["python", "-m", "uvicorn", "cloud.src.api_endpoints:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
