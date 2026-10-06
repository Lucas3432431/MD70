FROM docker.io/oven/bun:1-alpine AS development

ARG ENV
ARG HOT_RELOAD_ENABLED
ARG FRONTEND_PORT=5182

ENV ENV=${ENV} \
    HOT_RELOAD_ENABLED=${HOT_RELOAD_ENABLED} \
    FRONTEND_PORT=${FRONTEND_PORT} \
    CHOKIDAR_USEPOLLING=true \
    WATCHPACK_POLLING=true

WORKDIR /app

RUN apk upgrade --no-cache && apk add --no-cache curl bash ca-certificates

COPY package.json bun.lock* ./
RUN echo "📦 Installing frontend dependencies..." && \
    bun install --frozen-lockfile && \
    echo "✅ Done"

COPY . .

RUN mkdir -p /app/node_modules/.vite /app/node_modules/.vite-temp && \
    chown -R bun:bun /app

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

USER bun
EXPOSE ${FRONTEND_PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -sf http://localhost:${FRONTEND_PORT}/ || exit 1

ENTRYPOINT ["./entrypoint.sh"]
