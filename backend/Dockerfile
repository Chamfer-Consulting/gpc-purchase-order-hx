# PO Dashboard API. Build context is the REPO ROOT (not backend/) so the reused
# repo modules (qbo_matcher, product_catalog, dashboard/*, ...) are available.
#   docker build -f backend/Dockerfile -t po-dashboard-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Reused Python from the repo root + the (transitional) dashboard service layer.
COPY *.py ./
COPY dashboard/ ./dashboard/
COPY schema.sql ./schema.sql
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
