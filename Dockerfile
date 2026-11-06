FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROME_BIN=/usr/bin/chromium

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-sandbox \
    ffmpeg \
    curl \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 engdis && \
    useradd -u 1000 -g engdis -m -s /bin/bash engdis

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN mkdir -p /data/profile /data/cache /data/reports && \
    chown -R engdis:engdis /app /data && \
    chmod +x /app/docker/entrypoint.sh

USER engdis

VOLUME ["/data"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
