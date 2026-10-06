#!/bin/bash
# Production stack startup — split env em compose.env e app.secrets, apaga .env.production.
# Se .env.production não existir, usa secrets já gerados (deploys subsequentes).
#
# Usage: ./start_prod.sh [serviço...]
#        ./start_prod.sh            → build + up completo
#        ./start_prod.sh backend    → sobe só o backend
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"          # Infra/services/
SECRETS_DIR="$BASE_DIR/secrets"
COMPOSE_ENV="$SECRETS_DIR/compose.env"
APP_SECRETS="$SECRETS_DIR/app.secrets"
REDIS_CONF="$SECRETS_DIR/redis.conf"
ENV_PROD="$BASE_DIR/.env.production"
DB_DIR="$BASE_DIR/backend/Data"

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

# ── Atualizar secrets se .env.production presente ─────────────────────────────
if [ -f "$ENV_PROD" ]; then
    echo "▶ Encontrado .env.production — gerando secrets..."
    mkdir -p "$SECRETS_DIR"
    > "$COMPOSE_ENV"
    > "$APP_SECRETS"
    REDIS_PASSWORD=""

    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && { echo "$line" >> "$APP_SECRETS"; continue; }
        [[ -z "${line// }"            ]] && { echo ""      >> "$APP_SECRETS"; continue; }

        key="${line%%=*}"
        val="${line#*=}"

        if [ "$key" = "REDIS_PASSWORD" ]; then
            clean="${val%\"}"; clean="${clean#\"}"; clean="${clean%\'}"; clean="${clean#\'}"
            REDIS_PASSWORD="$clean"
        fi

        if printf '%s\n' "${COMPOSE_VARS[@]}" | grep -qx "$key"; then
            echo "$line" >> "$COMPOSE_ENV"
        else
            echo "$line" >> "$APP_SECRETS"
        fi
    done < "$ENV_PROD"

    chmod 600 "$APP_SECRETS" "$COMPOSE_ENV"
    echo "✔ secrets/compose.env e secrets/app.secrets atualizados"

    # frontend.secrets — apenas vars que o frontend precisa
    FRONTEND_SECRET_VARS=(
        LOG_LEVEL SESSION_ID LOG_ID LOG_TIMESTAMP LOG_RESPONSIBLE_FILE
        HOT_RELOAD LOG_SILENCE EXTERNAL_LOGGING SECURITY_FILTER
        STRIPE_PUBLISHABLE_KEY GOOGLE_AUTH_CLIENT_ID
    )
    > "$SECRETS_DIR/frontend.secrets"
    for fvar in "${FRONTEND_SECRET_VARS[@]}"; do
        grep -E "^${fvar}=" "$APP_SECRETS" >> "$SECRETS_DIR/frontend.secrets" || true
    done
    chmod 600 "$SECRETS_DIR/frontend.secrets"
    echo "✔ secrets/frontend.secrets gerado ($(wc -l < "$SECRETS_DIR/frontend.secrets") vars)"

    if [ -n "$REDIS_PASSWORD" ]; then
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
        echo "✔ secrets/redis.conf atualizado"
    else
        echo "⚠ REDIS_PASSWORD não encontrado — redis.conf não atualizado"
    fi

    rm -f "$ENV_PROD"
    echo "✔ .env.production removido do servidor"
else
    echo "⚠ .env.production não encontrado — usando secrets existentes"
fi

# ── Validação: secrets obrigatórios ───────────────────────────────────────────
[ ! -f "$COMPOSE_ENV"                   ] && { echo "✖ secrets/compose.env não encontrado. Coloque o .env.production no servidor e re-execute."; exit 1; }
[ ! -f "$APP_SECRETS"                   ] && { echo "✖ secrets/app.secrets não encontrado. Coloque o .env.production no servidor e re-execute."; exit 1; }
[ ! -f "$REDIS_CONF"                    ] && { echo "✖ secrets/redis.conf não encontrado. Coloque o .env.production no servidor e re-execute."; exit 1; }
[ ! -f "$SECRETS_DIR/frontend.secrets"  ] && { echo "✖ secrets/frontend.secrets não encontrado. Re-execute com .env.production para regenerar."; exit 1; }

# ── Ownership (rootless podman user namespace) ────────────────────────────────
echo "▶ Ajustando permissões do Data directory..."
mkdir -p "$DB_DIR/Database"
podman unshare chown -R 1000:1000 "$DB_DIR/"

echo "▶ Ajustando ownership dos secrets para os UIDs dos containers..."
podman unshare chown 999:999   "$REDIS_CONF"
podman unshare chown 1000:1000 "$APP_SECRETS"
podman unshare chown 1000:1000 "$SECRETS_DIR/frontend.secrets"

# ── Build + Up ────────────────────────────────────────────────────────────────
cd "$BASE_DIR"
source "$COMPOSE_ENV"

echo "▶ Build das imagens..."
podman build --network=host \
  -f "$BASE_DIR/frontend/Dockerfile" \
  -t localhost/md70-frontend:latest \
  --build-arg ENV="${ENV:-production}" \
  --build-arg HOT_RELOAD_ENABLED="${HOT_RELOAD_ENABLED:-false}" \
  --build-arg FRONTEND_PORT="${FRONTEND_PORT:-5082}" \
  "$BASE_DIR/frontend"
echo "✔ Frontend buildado"

podman-compose -p md70 --env-file "$COMPOSE_ENV" -f docker-compose.yml -f docker-compose.prod.yml build backend gateway sandbox egress_proxy browser

echo "▶ Iniciando containers..."
if [ "$#" -eq 0 ]; then
    podman-compose -p md70 --env-file "$COMPOSE_ENV" -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans egress_proxy browser sandbox redis backend frontend gateway
else
    podman-compose -p md70 --env-file "$COMPOSE_ENV" -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans "$@"
fi

echo "▶ Reiniciando gateway para re-resolver DNS dos upstreams..."
sleep 15
APP_VERSION="$(grep '^APP_VERSION=' "$COMPOSE_ENV" | cut -d= -f2)"
podman restart "md70_gateway_${APP_VERSION}" 2>/dev/null || true
echo "✔ Gateway reiniciado"

echo "✔ Deploy concluído."
