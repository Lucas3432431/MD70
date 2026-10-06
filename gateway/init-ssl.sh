#!/bin/sh
# 01-init-ssl.sh - Gera certificados se não existirem

DOMAIN_NAME="${DOMAIN_NAME:-localhost}"
SSL_DIR="/etc/nginx/ssl"
SSL_LIVE_PATH="${SSL_DIR}/live/${DOMAIN_NAME}"
SSL_CERT_FILE="${SSL_LIVE_PATH}/fullchain.pem"
SSL_KEY_FILE="${SSL_LIVE_PATH}/privkey.pem"

if [ ! -f "${SSL_CERT_FILE}" ]; then
    echo "📝 [SSL INIT] Gerando certificados para ${DOMAIN_NAME}..."
    mkdir -p "${SSL_LIVE_PATH}"
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${SSL_KEY_FILE}" \
        -out "${SSL_CERT_FILE}" \
        -subj "/C=BR/ST=SP/L=SaoPaulo/O=ZeraDev/CN=${DOMAIN_NAME}" \
        2>/dev/null
    echo "✅ [SSL INIT] Certificados gerados."
fi

# Ajusta permissões para que o Nginx consiga ler (mesmo se rodar como não-root)
chown -R nginx:nginx /etc/nginx/ssl /var/cache/nginx /var/log/nginx /tmp
chmod -R 755 /etc/nginx/ssl
