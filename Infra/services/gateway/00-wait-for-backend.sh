#!/bin/sh
# Aguarda DNS de backend e frontend resolverem antes do nginx iniciar.
# Em deploy limpo esses containers sobem depois do gateway, então nginx
# crasharia sem essa espera.
for HOST in "${BACKEND_HOST:-backend}" "${WEB_HOST:-frontend}"; do
    echo "[gateway] Waiting for DNS: $HOST ..."
    until getent hosts "$HOST" >/dev/null 2>&1; do
        sleep 2
    done
    echo "[gateway] DNS resolved: $HOST"
done
