FROM docker.io/library/python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl sqlite3 \
    && apt-get install -y --only-upgrade openssl libssl3t64 openssl-provider-legacy 2>/dev/null || true \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi uvicorn pydantic \
    pandas numpy requests tabulate python-dateutil openpyxl \
    sympy scipy matplotlib statsmodels scikit-learn \
    seaborn plotly kaleido \
    duckdb numpy-financial xgboost \
    sqlalchemy \
    prophet \
    pymupdf && \
    pip install --no-cache-dir 'jaraco.context>=6.1.0' 'wheel>=0.46.2'

RUN groupadd -g 1001 sandbox && \
    useradd -u 1001 -g sandbox -s /bin/bash -m sandbox && \
    mkdir -p /tmp/sandbox && chown sandbox:sandbox /tmp/sandbox

COPY --chown=sandbox:sandbox main.py .

USER sandbox

ARG SANDBOX_PORT=8001
ENV SANDBOX_PORT=${SANDBOX_PORT}

EXPOSE ${SANDBOX_PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 8001)); s.close()"

CMD ["python3", "main.py"]
