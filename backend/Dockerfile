# PO Dashboard API. Build context is the REPO ROOT (not backend/) so the reused
# repo modules (qbo_matcher, product_catalog, shared/*, ...) are available.
#   docker build -f backend/Dockerfile -t po-dashboard-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Reused Python: the repo-root modules + the three shared data modules in shared/.
COPY *.py ./
COPY shared/ ./shared/
COPY schema.sql ./schema.sql
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
# $PORT-aware so it runs on Railway / Fly / Render / plain docker unchanged.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
