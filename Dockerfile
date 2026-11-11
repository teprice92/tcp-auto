# Hosted deployment image (Azure Container Apps / App Service, or any container host).
FROM python:3.12-slim

WORKDIR /app
COPY backend/ backend/
COPY frontend/ frontend/
COPY rules/ rules/

RUN pip install --no-cache-dir ./backend \
 && python -m playwright install --with-deps chromium

ENV TCP_DATA_DIR=/data \
    TCP_RULES_DIR=/app/rules \
    TCP_FRONTEND_DIR=/app/frontend
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "tcp_auto.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
