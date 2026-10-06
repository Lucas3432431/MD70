FROM python:3.11-alpine

RUN apk upgrade --no-cache && \
    pip install --no-cache-dir 'jaraco.context>=6.1.0' 'wheel>=0.46.2'

RUN addgroup -g 1002 proxygrp && \
    adduser -D -u 1002 -G proxygrp proxyuser

WORKDIR /app
COPY proxy.py .

COPY healthcheck.py .

USER proxyuser
EXPOSE 3128
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 3128)); s.close()"

CMD ["python3", "proxy.py"]
