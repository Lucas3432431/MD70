#!/bin/bash
# Sobe o túnel Cloudflare do MD70 como container, dentro da máquina do Podman.
#
# Pré-requisitos:
#   - Credencial do túnel em ~/cloudflared/<TUNNEL_ID>.json
#     (gerada no Windows por `cloudflared tunnel create md70`, ver README.md)
#
# Uso (dentro da máquina: `podman machine ssh`):
#   ./Infra/TrafficTuneling/setup_tunnel.sh
set -euo pipefail

TUNNEL_ID="${TUNNEL_ID:-0ef4fe3c-875e-4893-ad30-2e4c742a18e1}"
HOSTNAME_PUBLIC="${HOSTNAME_PUBLIC:-md70.zera.tec.br}"
ORIGIN="${ORIGIN:-http://localhost:8080}"
IMAGE="${IMAGE:-docker.io/cloudflare/cloudflared:2026.10.0}"
DIR="$HOME/cloudflared"
NAME=md70_cloudflared

[ -f "$DIR/$TUNNEL_ID.json" ] || { echo "✖ $DIR/$TUNNEL_ID.json não encontrado (credencial do túnel)"; exit 1; }

cat > "$DIR/config.yml" <<EOF
tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $HOSTNAME_PUBLIC
    service: $ORIGIN
  - service: http_status:404
EOF

# A imagem roda como nonroot (uid 65532)
chmod 700 "$DIR"; chmod 600 "$DIR"/*
podman unshare chown -R 65532:65532 "$DIR"

podman rm -f "$NAME" >/dev/null 2>&1 || true
podman run -d --name "$NAME" --restart unless-stopped --network host \
  -v "$DIR:/etc/cloudflared:ro" \
  "$IMAGE" tunnel --no-autoupdate --config /etc/cloudflared/config.yml run

echo "▶ Aguardando conexões..."
sleep 10
podman logs "$NAME" 2>&1 | grep -E "Registered tunnel connection|ERR" | head -4
echo "✔ Túnel $TUNNEL_ID → $HOSTNAME_PUBLIC → $ORIGIN"
