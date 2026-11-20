# syntax=docker/dockerfile:1
# Fetch and compile an immutable version of Disane87/spoolman-mcp.
FROM node:24-alpine AS spoolman-build
RUN apk add --no-cache git
WORKDIR /build
ARG SPOOLMAN_UPSTREAM_SHA=18b511912f5d160bedbe0f5ec54217114e0653db
RUN git init -q \
    && git remote add origin https://github.com/Disane87/spoolman-mcp.git \
    && git fetch --no-tags --depth=1 origin "$SPOOLMAN_UPSTREAM_SHA" \
    && git checkout --detach FETCH_HEAD \
    && npm ci --no-audit --no-fund \
    && npm run build \
    && npm prune --omit=dev --no-audit --no-fund

FROM node:24-alpine AS proxy-build
WORKDIR /build
# Exact direct dependency version. Transitive packages resolve during image builds.
RUN npm install --no-save --omit=dev --no-audit --no-fund mcp-proxy@6.10.0

FROM node:24-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY --from=spoolman-build --chown=node:node /build/dist /app/spoolman/dist
COPY --from=spoolman-build --chown=node:node /build/node_modules /app/spoolman/node_modules
COPY --from=spoolman-build --chown=node:node /build/package.json /app/spoolman/package.json
COPY --from=proxy-build --chown=node:node /build/node_modules /app/proxy/node_modules
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/spoolman-mcp-entrypoint
USER node
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/spoolman-mcp-entrypoint"]
