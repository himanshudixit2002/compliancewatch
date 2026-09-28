# syntax=docker/dockerfile:1.7
# Build from the repo root:  docker build -f apps/whatsapp-bot/Dockerfile -t compliancewatch-whatsapp-bot .
# The root .dockerignore lets only this app and the workspace manifests into the context.
ARG NODE_VERSION=22

# ---- builder: install with the workspace lockfile, compile TypeScript -------------------------
FROM node:${NODE_VERSION}-alpine AS builder
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/
COPY packages/contracts/package.json packages/contracts/
COPY apps/whatsapp-bot/ apps/whatsapp-bot/
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter whatsapp-bot
RUN pnpm --filter whatsapp-bot build \
 && pnpm --filter whatsapp-bot deploy --prod --legacy /out

# ---- runtime: production dependencies and the compiled app, non-root ---------------------------
FROM node:${NODE_VERSION}-alpine AS runtime
ENV NODE_ENV=production PORT=8080
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app -H app
WORKDIR /app
COPY --from=builder --chown=app:app /out/dist ./dist
COPY --from=builder --chown=app:app /out/node_modules ./node_modules
COPY --from=builder --chown=app:app /out/package.json ./package.json
USER app
EXPOSE 8080
CMD ["node", "dist/index.js"]
