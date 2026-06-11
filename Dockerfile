FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY goldscanner ./goldscanner

# Default DB path lives on a mounted volume on Railway (see README).
ENV GOLDSCANNER_DB_PATH=/data/goldscanner.db

CMD ["python", "-m", "goldscanner.main"]
