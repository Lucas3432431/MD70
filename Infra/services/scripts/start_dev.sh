#!/bin/bash
# Dev stack startup — split env em compose.env (substituição YAML) e app.secrets (mount container).
#
# Usage: ./start_dev.sh [--env-file <arquivo>] [serviço...]
#        ./start_dev.sh
#        ./start_dev.sh backend frontend
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"          # Infra/services/
SECRETS_DIR="$BASE_DIR/secrets"
COMPOSE_ENV="$SECRETS_DIR/compose.env"
APP_SECRETS="$SECRETS_DIR/app.secrets"
REDIS_CONF="$SECRETS_DIR/redis.conf"
DB_DIR="$BASE_DIR/backend/Data"

# ── Args ─────────────────────────────────────────────────────────────────────
SOURCE_ENV="$BASE_DIR/.env.development"
REMAINING_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) SOURCE_ENV="$2"; shift 2 ;;
        *)          REMAINING_ARGS+=("$1"); shift ;;
    esac
done

[ ! -f "$SOURCE_ENV" ] && { echo "✖ Arquivo não encontrado: $SOURCE_ENV"; exit 1; }

# ── Vars que vão para compose.env (referenciadas no docker-compose.yml) ───────
COMPOSE_VARS=(
    APP_VERSION ANOMALY_INBOUND ANOMALY_OUTBOUND BACKEND_PORT
    BROWSER_EXPOSE_PORT DOMAIN_NAME INSTITUTIONAL_DOMAIN_NAME
    CARDAPIO_DOMAIN_NAME DELIVERY_DOMAIN_NAME ENV FRONTEND_PORT
    GATEWAY_BACKEND_HOST GATEWAY_FRONTEND_HOST GATEWAY_HTTPS_PORT GATEWAY_HTTP_PORT
    GATEWAY_WEB_HOST GATEWAY_WEB_PORT
    HOT_RELOAD_ENABLED LITESTREAM_ENABLED NGINX_PORT PUBLIC_URL
    REDIS_HOST REDIS_INTERNAL_PORT REDIS_PORT SANDBOX_EXPOSE_PORT
    VITE_DOMAIN VITE_HTTP_PROTOCOL
)

# ── Split do env em dois arquivos ─────────────────────────────────────────────
echo "▶ Gerando secrets a partir de $SOURCE_ENV..."
mkdir -p "$SECRETS_DIR"
podman unshare chown 0:0 "$APP_SECRETS" 2>/dev/null || true
podman unshare chown 0:0 "$COMPOSE_ENV" 2>/dev/null || true
> "$COMPOSE_ENV"
> "$APP_SECRETS"
REDIS_PASSWORD=""
APP_VERSION=""

while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && { echo "$line" >> "$APP_SECRETS"; continue; }
    [[ -z "${line// }"            ]] && { echo ""      >> "$APP_SECRETS"; continue; }

    key="${line%%=*}"
    val="${line#*=}"

    if [ "$key" = "REDIS_PASSWORD" ]; then
        clean="${val%\"}"; clean="${clean#\"}"; clean="${clean%\'}"; clean="${clean#\'}"
        REDIS_PASSWORD="$clean"
    fi

    if [ "$key" = "APP_VERSION" ]; then
        APP_VERSION="${val}"
    fi

    if printf '%s\n' "${COMPOSE_VARS[@]}" | grep -qx "$key"; then
        echo "$line" >> "$COMPOSE_ENV"
    else
        echo "$line" >> "$APP_SECRETS"
    fi
done < "$SOURCE_ENV"

chmod 600 "$APP_SECRETS" "$COMPOSE_ENV"
podman unshare chown 1000:1000 "$APP_SECRETS"
echo "✔ secrets/compose.env e secrets/app.secrets atualizados"

# ── redis.conf ────────────────────────────────────────────────────────────────
if [ -n "$REDIS_PASSWORD" ]; then
    podman unshare chown 0:0 "$REDIS_CONF" 2>/dev/null || true
    rm -f "$REDIS_CONF"
    cat > "$REDIS_CONF" <<EOF
requirepass $REDIS_PASSWORD

maxmemory 512mb
maxmemory-policy allkeys-lru
protected-mode yes
appendonly yes

rename-command FLUSHALL ""
rename-command FLUSHDB ""
rename-command DEBUG ""
rename-command SHUTDOWN ""
EOF
    chmod 600 "$REDIS_CONF"
    podman unshare chown 999:999 "$REDIS_CONF"
    echo "✔ secrets/redis.conf atualizado"
else
    echo "⚠ REDIS_PASSWORD não encontrado — redis.conf não atualizado"
fi

# ── Ownership da pasta de dados (rootless podman) ─────────────────────────────
echo "▶ Ajustando permissões do Data directory..."
mkdir -p "$DB_DIR/Database"
podman unshare chown -R 1000:1000 "$DB_DIR/"

# ── Remove containers com imagem desatualizada ────────────────────────────────
echo "▶ Verificando containers com imagem desatualizada..."
stale_found=0
while IFS=' ' read -r cname image_ref; do
    current_id=$(podman image inspect --format '{{.Id}}' "$image_ref" 2>/dev/null || true)
    [ -z "$current_id" ] && continue
    running_id=$(podman inspect --format '{{.Image}}' "$cname" 2>/dev/null || true)
    [ -z "$running_id" ] && continue
    if [ "$current_id" != "$running_id" ]; then
        echo "  ↻ $cname usa imagem antiga — será recriado"
        podman rm -f "$cname" 2>/dev/null || true
        stale_found=1
    fi
done < <(podman ps -a --filter "label=io.podman.compose.project=md70" \
             --format '{{.Names}} {{.Image}}' 2>/dev/null)

if [ "$stale_found" -eq 1 ]; then
    while IFS=' ' read -r cname state; do
        if [[ "$state" == "exited" || "$state" == "created" ]]; then
            podman rm -f "$cname" 2>/dev/null || true
        fi
    done < <(podman ps -a --filter "label=io.podman.compose.project=md70" \
                 --format '{{.Names}} {{.State}}' 2>/dev/null)
    echo "✔ Containers desatualizados removidos"
else
    echo "✔ Todos os containers estão na imagem atual"
fi

# ── Up ────────────────────────────────────────────────────────────────────────
echo "▶ Iniciando stack de desenvolvimento..."
cd "$BASE_DIR"
if [ "${#REMAINING_ARGS[@]}" -eq 0 ]; then
    SERVICES=(egress_proxy browser sandbox redis backend frontend gateway)
else
    SERVICES=("${REMAINING_ARGS[@]}")
fi
podman-compose -p md70 --env-file "$COMPOSE_ENV" -f docker-compose.yml -f docker-compose.dev.yml up -d "${SERVICES[@]}"

# Reinicia o gateway para re-resolver DNS dos containers recriados
GATEWAY_NAME="md70_gateway_${APP_VERSION}"
if podman inspect "$GATEWAY_NAME" &>/dev/null; then
    echo "▶ Reiniciando gateway para re-resolver DNS..."
    podman restart "$GATEWAY_NAME" &>/dev/null && echo "✔ Gateway reiniciado." || echo "⚠ Falha ao reiniciar gateway."
fi

echo "✔ Stack dev iniciada."
