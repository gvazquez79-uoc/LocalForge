# ── LocalForge Backend ────────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# System deps (needed by some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY backend/ ./backend/
COPY localforge.json .

# Data directory for SQLite DB and memory file
RUN mkdir -p /data

# Default env — override via docker-compose or .env
ENV LOCALFORGE_HOST=0.0.0.0
ENV LOCALFORGE_PORT=8000
ENV DATA_DIR=/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
