FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS api

COPY backend ./backend
COPY dist ./dist

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS crawler

COPY requirements-crawler.txt ./
RUN pip install --no-cache-dir -r requirements-crawler.txt

COPY dist ./dist
COPY parser ./parser

CMD ["python", "parser/crawl_admission_rules.py", "--limit", "10"]
