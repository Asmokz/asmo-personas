FROM python:3.11-slim

WORKDIR /app

COPY commons/ /commons/
RUN pip install --no-cache-dir /commons/

COPY giorgio/ /app/
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.main"]
