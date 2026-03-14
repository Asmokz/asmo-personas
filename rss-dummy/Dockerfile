FROM python:3.11-slim

WORKDIR /app

COPY rss-dummy/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY rss-dummy/src/ /app/src/
COPY rss-dummy/config/ /app/config/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.main"]
