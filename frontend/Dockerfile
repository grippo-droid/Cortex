# Multi-stage so the runtime image carries the built app and nothing else: no
# toolchain, no dev dependencies, no source.

FROM node:22-alpine AS deps
WORKDIR /app
# Only the manifests, so this layer is reused whenever dependencies are unchanged.
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# The browser-facing API URL. This has to be a build argument rather than a
# runtime variable: Next inlines NEXT_PUBLIC_* values into the client bundle at
# build time, so setting it at runtime does nothing at all. The default suits a
# developer running compose locally, where the browser reaches the API on the
# published port rather than the compose network.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Run as a non-root user: nothing here needs privileges.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=builder /app/public ./public
# `output: "standalone"` produces server.js plus only the dependencies it
# actually reaches; static assets are emitted separately and are not included.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
