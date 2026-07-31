# One container, two processes: the Python pipeline API (src/ingest_server.py)
# on an internal-only port, and the Next.js production UI (web/) on Railway's
# public $PORT — the UI's server-side proxy talks to the API over localhost.
# Deliberately one Railway service instead of two: this is a small app, and
# managing two separately-deployed services for it was more overhead than
# the app warrants.

FROM node:22-bookworm-slim AS web-deps
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM node:22-bookworm-slim AS web-builder
WORKDIR /app/web
COPY --from=web-deps /app/web/node_modules ./node_modules
COPY web/ .
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV PIPELINE_PORT=8081

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .
RUN rm -rf web
RUN cd remotion && npm install

# Next.js UI, already built in web-builder.
COPY --from=web-builder /app/web/.next ./web/.next
COPY --from=web-builder /app/web/node_modules ./web/node_modules
COPY --from=web-builder /app/web/package.json ./web/package.json
COPY --from=web-builder /app/web/public ./web/public

RUN chmod +x docker-entrypoint.sh

EXPOSE 8080
CMD ["./docker-entrypoint.sh"]
