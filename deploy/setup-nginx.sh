#!/bin/bash
# =============================================================================
# Configura nginx como proxy inverso para LocalForge
# Edita DOMAIN y PROJECT_DIR antes de ejecutar
# =============================================================================
set -e

DOMAIN="${1:-tu-servidor.com}"          # pasa el dominio como argumento
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🌐 Configurando nginx para dominio: $DOMAIN"
echo "📁 Directorio del proyecto: $PROJECT_DIR"

sudo tee /etc/nginx/sites-available/localforge > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    # Archivos estáticos del frontend (build de Vite)
    root $PROJECT_DIR/frontend/dist;
    index index.html;

    # Todas las rutas de la SPA → index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy de la API al backend (uvicorn en puerto 8000)
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;

        # SSE (Server-Sent Events) — crucial para el streaming del chat
        proxy_buffering          off;
        proxy_cache              off;
        proxy_read_timeout       300s;
        proxy_connect_timeout    10s;
        chunked_transfer_encoding on;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/localforge /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "✅ nginx configurado."
echo ""
echo "Para HTTPS con Let's Encrypt:"
echo "  sudo apt install certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d $DOMAIN"
