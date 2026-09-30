ARG BASE=python:3.11-slim

# ---- 1. Build the web interface (React + Vite -> static files)
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. The server (FastAPI serves the built interface; no Node at runtime)
FROM ${BASE}
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY tests tests
COPY tools tools
COPY --from=web /web/dist frontend/dist
COPY frontend/public/samples frontend/public/samples
RUN mkdir -p /data
EXPOSE 8000
# One worker only: interview locks live in process memory.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
