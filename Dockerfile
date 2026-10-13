FROM node:24-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend:/app PLAYWRIGHT_BROWSERS_PATH=/ms-playwright TRACE_DATA=/data
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && python -m playwright install --with-deps chromium \
    && useradd -m -u 10001 trace && mkdir /data && chown trace:trace /data
COPY backend/ backend/
COPY scripts/ scripts/
COPY tests/ tests/
COPY deploy/verify_isolation.py deploy/verify_isolation.py
COPY --from=ui /ui/dist frontend/dist/
USER trace
CMD ["python","-m","uvicorn","traceapp.api:app","--host","0.0.0.0","--port","8000","--no-access-log"]
