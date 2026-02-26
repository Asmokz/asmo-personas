FROM python:3.11-slim

# System packages needed for monitoring tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    iproute2 \
    sysstat \
    smartmontools \
    && rm -rf /var/lib/apt/lists/*
# Note: Docker operations use the Python SDK (docker>=6.0.0) via the socket
# mount — no CLI binary required.

WORKDIR /app

# Install commons first (cached layer)
COPY commons/ /commons/
RUN pip install --no-cache-dir /commons/

# Install bot
COPY femto/ /app/
RUN pip install --no-cache-dir -e .

# Data directory for metrics persistence
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.main"]
