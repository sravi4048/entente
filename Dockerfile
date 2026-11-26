# ---- 1. build the React frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime: FastAPI + Diplomacy adjudicator
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    DATA_DIR=/data \
    HOME=/home/entente \
    PORT=8000
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
RUN mkdir -p /data && useradd --create-home --uid 1000 entente && chown -R entente /data /app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')"
# Starts as root only to chown the mounted volume (Fly/Docker volumes mount root-owned),
# then drops to the unprivileged user.
# One worker on purpose: websockets and the deadline scheduler live in-process.
CMD ["sh", "-c", "chown -R entente:entente \"$DATA_DIR\" && exec setpriv --reuid=entente --regid=entente --init-groups uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
