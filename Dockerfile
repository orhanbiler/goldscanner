# ---- Stage 1: build the React (Vite + shadcn) frontend ----
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY goldscanner ./goldscanner
# Bake the built UI into the image where the app looks for it first.
COPY --from=frontend /frontend/dist ./goldscanner/web_dist

# Default DB path lives on a mounted volume on Railway (see README).
ENV GOLDSCANNER_DB_PATH=/data/goldscanner.db

CMD ["python", "-m", "goldscanner.main"]
