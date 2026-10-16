FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx pillow

COPY gemini_web2api /app/gemini_web2api
COPY pool_manager.py /app/pool_manager.py
COPY pool_server.py /app/pool_server.py
COPY static /app/static

RUN mkdir -p /app/data && chmod 700 /app/data

ENV PORT=8095
ENV HOST=0.0.0.0
ENV GEMINI_POOL_DB=/app/data/gemini_pool.db

EXPOSE 8095

CMD ["python", "pool_server.py"]
