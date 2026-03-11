FROM python:3.11-slim

WORKDIR /app

# System deps for yfinance (lxml), beautifulsoup4 and hiredis
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY commons/ /commons/
RUN pip install --no-cache-dir /commons/

COPY vegas/ /app/
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Volume for SQLite databases
VOLUME ["/data"]

CMD ["python", "-m", "src.main"]
