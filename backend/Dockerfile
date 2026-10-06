FROM docker.io/library/python:3.11-slim AS deps
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --root-user-action=ignore -r requirements.txt && \
    pip install --no-cache-dir 'jaraco.context>=6.1.0' 'wheel>=0.46.2'

FROM docker.io/library/python:3.11-slim AS runtime
ARG BACKEND_PORT
ARG ENV
ARG HOT_RELOAD_ENABLED

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=on \
    ENV=${ENV} \
    BACKEND_PORT=${BACKEND_PORT} \
    HOT_RELOAD_ENABLED=${HOT_RELOAD_ENABLED} \
    PYTHONPATH=/app:/app/src

WORKDIR /app

# Instala Litestream e aplica upgrades de segurança disponíveis
# curl mantido: necessário para o healthcheck do docker-compose
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends curl \
    && apt-get install -y --only-upgrade openssl libssl3t64 openssl-provider-legacy 2>/dev/null || true \
    && LITESTREAM_VERSION=0.5.13 \
    && curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

RUN find /usr/local/lib/python3.11/site-packages -maxdepth 1 -name "wheel-0.[0-4][0-5]*.dist-info" -exec rm -rf {} + 2>/dev/null || true

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .
RUN chmod +x entrypoint.sh

USER appuser
EXPOSE ${BACKEND_PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 4001)); s.close()"

ENTRYPOINT ["./entrypoint.sh"]
