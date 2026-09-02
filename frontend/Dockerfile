# ─── Stage 1: Dependencies & Build ─────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package descriptors
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies for build)
RUN npm install

# Copy application source
COPY . .

# Set default API URL environment variable for build time
ENV NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1

# Build Next.js application
RUN npm run build

# ─── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Copy necessary files from builder
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.js ./next.config.js
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

CMD ["npm", "run", "start"]
