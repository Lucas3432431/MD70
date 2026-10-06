FROM docker.io/owasp/modsecurity-crs:nginx-alpine

USER root
RUN apk upgrade --no-cache && apk add --no-cache openssl su-exec

# Injeta o carregamento dos módulos no topo do nginx.conf oficial
RUN sed -i '1i load_module modules/ngx_http_modsecurity_module.so;' /etc/nginx/nginx.conf && \
    sed -i '1i load_module modules/ngx_http_headers_more_filter_module.so;' /etc/nginx/nginx.conf

# Copia nosso template
COPY gateway.conf.template /etc/nginx/templates/conf.d/gateway.conf.template

# Exclusão CRS
COPY REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf \
     /etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf

# Aguarda DNS do backend antes de iniciar o nginx
COPY 00-wait-for-backend.sh /docker-entrypoint.d/00-wait-for-backend.sh
RUN chmod +x /docker-entrypoint.d/00-wait-for-backend.sh

# Hook de SSL
COPY init-ssl.sh /docker-entrypoint.d/01-init-ssl.sh
RUN chmod +x /docker-entrypoint.d/01-init-ssl.sh

# Prepara permissões para rodar como non-root
# Nginx alpine usa o UID 101 para o user nginx
RUN mkdir -p /etc/nginx/ssl /var/cache/nginx /var/log/nginx /var/run /tmp/modsecurity /etc/nginx/conf.d /etc/nginx/modsecurity.d && \
    chown -R nginx:nginx /etc/nginx /var/cache/nginx /var/log/nginx /var/run /usr/share/nginx /tmp/modsecurity && \
    chmod -R 775 /etc/nginx /var/cache/nginx /var/log/nginx /var/run /tmp/modsecurity

# Garante log do modsec
RUN touch /var/log/modsec_audit.log && chown nginx:nginx /var/log/modsec_audit.log

USER nginx

EXPOSE 8081 8443
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD nginx -t 2>/dev/null || exit 1
