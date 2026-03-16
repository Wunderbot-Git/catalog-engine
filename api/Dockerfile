FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/ ./api/

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "cd api && alembic upgrade head 2>&1 || echo 'Alembic migration skipped'; cd /app && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
