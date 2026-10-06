#!/bin/bash
# Religa o stack de produção já criado (sem build) — usado no boot do Windows,
# depois de `podman machine start`. Para deploy/atualização use start_prod.sh.
#
# Usage: ./boot_prod.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"          # Infra/services/
COMPOSE_ENV="$BASE_DIR/secrets/compose.env"

[ -f "$COMPOSE_ENV" ] || { echo "✖ secrets/compose.env não encontrado — rode start_prod.sh primeiro"; exit 1; }
APP_VERSION="$(grep '^APP_VERSION=' "$COMPOSE_ENV" | cut -d= -f2)"

wait_healthy() {
    local name="$1" timeout="${2:-180}" status
    for ((i = 0; i < timeout; i += 3)); do
        status="$(podman inspect "$name" --format '{{.State.Health.Status}}' 2>/dev/null)"
        [ "$status" = "healthy" ] && { echo "  ✔ $name healthy"; return 0; }
        sleep 3
    done
    echo "  ⚠ $name não ficou healthy em ${timeout}s (status: ${status:-?})"
    return 1
}

start() {
    local name="$1"
    if podman container exists "$name"; then
        podman start "$name" >/dev/null && echo "▶ $name"
    else
        echo "✖ $name não existe — rode start_prod.sh (ou setup_tunnel.sh para o túnel)"
    fi
}

# Túnel primeiro: com ele no ar o domínio responde 502 em vez de 530 enquanto o resto sobe
start md70_cloudflared

# Mesma ordem dos depends_on do docker-compose.yml
start "md70_egress_proxy_${APP_VERSION}"; wait_healthy "md70_egress_proxy_${APP_VERSION}" 60
start "md70_redis_${APP_VERSION}"
start "md70_browser_${APP_VERSION}"
start "md70_sandbox_${APP_VERSION}"
wait_healthy "md70_redis_${APP_VERSION}" 60
wait_healthy "md70_sandbox_${APP_VERSION}" 120
wait_healthy "md70_browser_${APP_VERSION}" 120
start "md70_backend_${APP_VERSION}"; wait_healthy "md70_backend_${APP_VERSION}" 180
# frontend faz `vite build` a cada start (ver frontend/entrypoint.sh)
start "md70_frontend_${APP_VERSION}"; wait_healthy "md70_frontend_${APP_VERSION}" 600
start "md70_gateway_${APP_VERSION}";  wait_healthy "md70_gateway_${APP_VERSION}" 120

podman ps --format '{{.Names}} | {{.Status}}'
