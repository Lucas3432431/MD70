#!/bin/bash
set -e

# Carrega secrets mas NÃO sobrescreve vars já injetadas pelo compose (ex: VITE_DOMAIN, ENV).
# Filter out invalid bash variable names (e.g. "2FA=true" starts with digit).
if [ -f /run/secrets/app.env ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || continue
        [ -z "${!key+x}" ] && export "$key=$value"
    done < <(grep -E '^[a-zA-Z_][a-zA-Z0-9_]*=' /run/secrets/app.env)
fi

echo "🚀 BACKEND - Iniciando entrypoint v1.0..."
echo "🔧 Mode: ${ENV}"
echo "✅ Hot Reload: ${HOT_RELOAD_ENABLED}"
echo "🔄 Litestream: ${LITESTREAM_ENABLED:-false}"
echo "════════════════════════════════════════════════════════════"

[ ! -f "Main.py" ] && echo "❌ Main.py missing (check volume mount)" && exit 1

# Ensure DB directory exists and is writable (created here if first deploy)
mkdir -p /app/Data/Database

# Litestream: restaura backup se db não existe localmente
if [ "${LITESTREAM_ENABLED:-false}" = "true" ]; then
    if [ ! -f "/app/Data/Database/MD70.db" ]; then
        echo "📥 Restaurando banco do backup S3..."
        litestream restore -if-replica-exists -config /app/litestream.yml \
            /app/Data/Database/MD70.db \
            && echo "✅ Banco restaurado." \
            || echo "⚠️  Sem backup remoto, iniciando com banco novo."
    fi
fi

# Start Application
# Quando HOT_RELOAD_ENABLED=true, o uvicorn StatReload (configurado em HotReload.py)
# já monitora App/**/*.py e reinicia apenas o worker, mantendo o master vivo.
# O watchdog externo (watchmedo) matava o processo inteiro em paralelo ao StatReload,
# causando dois restarts consecutivos (~21s de 502 em vez de ~5s).
if [ "${LITESTREAM_ENABLED:-false}" = "true" ]; then
    if [ "${HOT_RELOAD_ENABLED}" = "true" ]; then
        echo "⚡ Starting Litestream + backend (hot reload via uvicorn StatReload)..."
        exec litestream replicate -config /app/litestream.yml -exec "python Main.py"
    else
        echo "🚀 Starting Litestream + backend (production)..."
        exec litestream replicate -config /app/litestream.yml -exec "python Main.py"
    fi
else
    if [ "${HOT_RELOAD_ENABLED}" = "true" ]; then
        echo "⚡ Starting backend (hot reload via uvicorn StatReload)..."
        exec python Main.py
    else
        echo "🚀 Starting backend in production mode..."
        exec python Main.py
    fi
fi
