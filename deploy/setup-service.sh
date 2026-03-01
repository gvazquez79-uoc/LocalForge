#!/bin/bash
# =============================================================================
# Crea un servicio systemd para mantener LocalForge corriendo
# =============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(whoami)}"

echo "⚙️  Creando servicio systemd para LocalForge..."
echo "📁 Directorio: $PROJECT_DIR"
echo "👤 Usuario: $SERVICE_USER"

sudo tee /etc/systemd/system/localforge.service > /dev/null <<EOF
[Unit]
Description=LocalForge AI Agent
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5

# Variables de entorno (lee automáticamente el .env del proyecto)
EnvironmentFile=-$PROJECT_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable localforge

echo ""
echo "✅ Servicio creado."
echo ""
echo "Comandos útiles:"
echo "  sudo systemctl start localforge    # arrancar"
echo "  sudo systemctl stop localforge     # parar"
echo "  sudo systemctl restart localforge  # reiniciar"
echo "  sudo systemctl status localforge   # estado"
echo "  journalctl -u localforge -f        # ver logs en tiempo real"
