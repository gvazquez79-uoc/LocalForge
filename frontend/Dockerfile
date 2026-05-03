# ── LocalForge Frontend — build + nginx ───────────────────────────────────────

# Stage 1: build
FROM node:22-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .

# In production, the frontend calls /api/ (relative) — nginx proxies it to backend
ENV VITE_API_BASE=/api

RUN npm run build

# Stage 2: serve with nginx
FROM nginx:alpine

# Remove default nginx site
RUN rm /etc/nginx/conf.d/default.conf

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/localforge.conf

# Copy built frontend
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
