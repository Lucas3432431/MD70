#!/usr/bin/env bash
set -e

PORT=8090
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://localhost:${PORT}/validate_og.html"

# Mata qualquer processo que já esteja usando a porta
fuser -k "${PORT}/tcp" 2>/dev/null || true

# Inicia o servidor em background
python3 -m http.server "${PORT}" --directory "${DIR}" &
SERVER_PID=$!

# Aguarda o servidor estar pronto
for i in $(seq 1 10); do
  curl -sf "http://localhost:${PORT}/" > /dev/null 2>&1 && break
  sleep 0.3
done

# Abre o browser
if command -v xdg-open &>/dev/null; then
  xdg-open "${URL}"
elif command -v open &>/dev/null; then
  open "${URL}"
fi

echo "Servidor rodando em ${URL} (PID ${SERVER_PID})"
echo "Ctrl+C para parar."

wait "${SERVER_PID}"
