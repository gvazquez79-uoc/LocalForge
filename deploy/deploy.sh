#!/bin/bash
# =============================================================================
# LocalForge — Script de despliegue en Linux (Ubuntu/Debian)
# Uso: bash deploy.sh
# =============================================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "📁 Directorio del proyecto: $REPO_DIR"

# ── 1. Instalar dependencias del sistema ──────────────────────────────────────
echo "📦 Actualizando paquetes del sistema..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv nodejs npm nginx 2>/dev/null || true

# ── 2. Backend: entorno virtual + dependencias ────────────────────────────────
echo "🐍 Configurando entorno virtual de Python..."
cd "$REPO_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet fastapi uvicorn anthropic openai duckduckgo-search \
    aiosqlite pydantic-settings python-dotenv pypdf python-telegram-bot

# ── 3. Frontend: build de producción ─────────────────────────────────────────
echo "⚛️  Construyendo el frontend..."
cd "$REPO_DIR/frontend"
npm install --silent
# API_BASE vacío = URL relativa /api (nginx hace el proxy)
VITE_API_BASE=/api npm run build

echo ""
echo "✅ Build completado."
echo ""
echo "Próximos pasos:"
echo "  1. Copia localforge.json y .env al servidor"
echo "  2. Configura nginx: bash deploy/setup-nginx.sh"
echo "  3. Configura el servicio: bash deploy/setup-service.sh"
echo "  4. Inicia: sudo systemctl start localforge"
