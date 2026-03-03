FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt-dev \
    ffmpeg \
    sysstat \
    smartmontools \
    curl \
    gnupg \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian bookworm stable" \
    > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# 1. Install shared commons
COPY commons/ /commons/
RUN pip install --no-cache-dir /commons/

# 2. Install all Python deps needed by Olympus + all personas
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    "uvicorn[standard]>=0.27.0" \
    python-multipart>=0.0.9 \
    aiosqlite>=0.19.0 \
    aiohttp>=3.9.0 \
    yfinance>=0.2.30 \
    spotipy>=2.23.0 \
    numpy>=1.26.0 \
    html2text>=2024.2.26 \
    "redis[hiredis]>=5.0.0" \
    faster-whisper>=1.0.0 \
    sqlalchemy>=2.0.0 \
    pymysql>=1.1.0 \
    structlog>=23.3.0 \
    "pydantic-settings>=2.0.0"

# 3. Copy all source trees (all accessed via PYTHONPATH=/app)
COPY olympus/src/ /app/olympus/src/
COPY alita/src/   /app/alita/src/
COPY femto/src/   /app/femto/src/
COPY giorgio/src/ /app/giorgio/src/

# 4. Copy built Vue.js frontend
# Pre-build with: cd olympus/frontend && npm install && npm run build
# If dist/ does not exist, the API still works — frontend simply won't be served.
RUN mkdir -p /app/olympus/frontend/dist

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

VOLUME ["/data"]
EXPOSE 8484

CMD ["python", "-m", "uvicorn", "olympus.src.main:app", \
     "--host", "0.0.0.0", "--port", "8484", "--no-access-log"]
