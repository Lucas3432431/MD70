#!/bin/bash
set -e

if [ -f /run/secrets/app.env ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || continue
        [ -z "${!key+x}" ] && export "$key=$value"
    done < <(grep -E '^[a-zA-Z_][a-zA-Z0-9_]*=' /run/secrets/app.env)
fi

echo "🚀 MD70 Frontend — Bun + TanStack Start"
echo "⚡ Dev server: http://localhost:${FRONTEND_PORT}"
echo "🔧 Mode: ${ENV:-development}"
echo "════════════════════════════════════════"

[ ! -f "/app/package.json" ] && echo "❌ package.json missing" && exit 1
[ ! -d "/app/src" ]         && echo "❌ src/ missing"          && exit 1

mkdir -p /tmp/vite-cache /tmp/vite-temp
export VITE_CACHE_DIR=/tmp/vite-cache

if [ "$HOT_RELOAD_ENABLED" = "true" ]; then
    echo "🚀 Starting Bun dev server..."
    bun run dev --host 0.0.0.0 --port "${FRONTEND_PORT}" --strictPort
else
    # O preset padrão do @lovable.dev/vite-tanstack-config é cloudflare-module (bundle de Worker),
    # que não roda self-hosted. NITRO_PRESET=bun gera .output/server/index.mjs executável pelo bun.
    export NITRO_PRESET="${NITRO_PRESET:-bun}"
    echo "🏗️  Building (nitro preset: ${NITRO_PRESET})..."
    bun run build
    echo "✅ Build done — serving .output/server/index.mjs"
    HOST=0.0.0.0 PORT="${FRONTEND_PORT}" exec bun .output/server/index.mjs
fi
