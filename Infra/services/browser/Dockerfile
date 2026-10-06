# Imagem oficial do Playwright com Chromium, Firefox e WebKit pré-instalados.
# Usa Ubuntu Noble (24.04) com usuário não-root "pwuser" (uid 1000).
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

# Sistema: chromedriver para selenium/undetected-chromedriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium-driver \
    && chmod a+rx /usr/bin/chromedriver \
    && (chmod a+rx /usr/bin/chromium 2>/dev/null || chmod a+rx /usr/bin/chromium-browser 2>/dev/null || true) \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    markdownify \
    "beautifulsoup4[lxml]" \
    lxml \
    trafilatura \
    setuptools \
    selenium \
    undetected-chromedriver \
    webdriver-manager \
    "playwright==1.60.0" \
    playwright-stealth \
    "curl-cffi>=0.7"

WORKDIR /app
COPY main.py .

USER pwuser
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 8002)); s.close()"

CMD ["python", "main.py"]
