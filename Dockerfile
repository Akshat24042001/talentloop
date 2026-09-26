ARG BASE=python:3.11-slim
FROM ${BASE}
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY web web
COPY tests tests
COPY tools tools
RUN mkdir -p /data
EXPOSE 8000
# One worker only: interview locks live in process memory.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
