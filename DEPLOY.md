# Despliegue de LocalForge en un servidor Linux

## Requisitos del servidor

- Ubuntu 20.04+ / Debian 11+ (o similar)
- 1 GB RAM mínimo (2+ recomendado si usas Ollama local)
- Python 3.10+, Node.js 18+, nginx
- Acceso SSH y permisos sudo

---

## Opción A: Despliegue rápido (todo en un puerto, sin nginx)

Ideal para uso personal/pruebas. Accedes por `http://IP:8000`.

```bash
# 1. Clonar el repositorio en el servidor
git clone https://github.com/tu-usuario/LocalForge.git
cd LocalForge

# 2. Crear entorno virtual e instalar dependencias Python
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn anthropic openai duckduckgo-search \
    aiosqlite pydantic-settings python-dotenv pypdf python-telegram-bot

# 3. Construir el frontend (API en la misma IP:puerto)
cd frontend
npm install
VITE_API_BASE=http://TU-IP:8000/api npm run build
cd ..

# 4. Crear configuración
cp localforge.example.json localforge.json
# Editar localforge.json: modelos, rutas permitidas, etc.
nano localforge.json

# 5. Crear .env con tus claves
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 6. Arrancar el servidor (escuchando en todas las IPs)
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Accede en `http://TU-IP:8000` 🎉

> ⚠️ Sin HTTPS las peticiones van sin cifrar. No expongas datos sensibles.

---

## Opción B: Producción con nginx + systemd (recomendado)

### 1. Preparar el servidor

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv nodejs npm nginx
```

### 2. Clonar y configurar

```bash
git clone https://github.com/tu-usuario/LocalForge.git /opt/localforge
cd /opt/localforge

# Entorno Python
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn anthropic openai duckduckgo-search \
    aiosqlite pydantic-settings python-dotenv pypdf python-telegram-bot

# Configuración
cp localforge.example.json localforge.json
nano localforge.json   # ajusta modelos, rutas, etc.

# Secretos
nano .env
# Contenido:
#   ANTHROPIC_API_KEY=sk-ant-...
#   CORS_ORIGINS=*
```

### 3. Construir el frontend

Con nginx, la API y el frontend están en el **mismo dominio** → URL relativa `/api`:

```bash
cd /opt/localforge/frontend
npm install
VITE_API_BASE=/api npm run build
```

Esto genera `frontend/dist/` con los archivos estáticos.

### 4. Configurar nginx

```bash
bash /opt/localforge/deploy/setup-nginx.sh tu-dominio.com
# o con IP:
# bash deploy/setup-nginx.sh 123.45.67.89
```

O manualmente:

```nginx
# /etc/nginx/sites-available/localforge
server {
    listen 80;
    server_name tu-dominio.com;

    root /opt/localforge/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_buffering    off;          # ← importante para SSE/streaming
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/localforge /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Crear servicio systemd

```bash
sudo bash /opt/localforge/deploy/setup-service.sh
sudo systemctl start localforge
sudo systemctl status localforge
```

### 6. HTTPS con Let's Encrypt (opcional pero recomendado)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
# Certbot renueva automáticamente el certificado
```

---

## Opción C: Con Ollama en el servidor

Si el servidor tiene GPU (o quieres modelos locales):

```bash
# Instalar Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Descargar modelos
ollama pull llama3.2
ollama pull qwen2.5:3b

# Ollama escucha en localhost:11434 por defecto
# Ya está configurado en localforge.json con base_url: http://localhost:11434/v1
```

> En un VPS sin GPU los modelos serán lentos. Se recomienda usar APIs (Anthropic/OpenAI) en servidores cloud.

---

## Variables de entorno (`.env`)

Solo necesitas las variables de los servicios que uses:

| Variable | Cuándo es necesaria | Ejemplo |
|----------|---------------------|---------|
| `API_KEY` | **Siempre en producción** — protege el acceso a la app | `mi-clave-secreta` |
| `CORS_ORIGINS` | Si usas nginx (mismo dominio) o acceso desde otro origen | `*` |
| `ANTHROPIC_API_KEY` | Solo si usas modelos Claude (Anthropic) | `sk-ant-...` |
| `OPENAI_API_KEY` | Solo si usas modelos OpenAI | `sk-...` |

**Ejemplo mínimo con solo Ollama** (sin ninguna API externa):
```env
API_KEY=mi-clave-secreta
CORS_ORIGINS=*
```

**Ejemplo con Claude + Ollama:**
```env
API_KEY=mi-clave-secreta
CORS_ORIGINS=*
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Actualizar LocalForge

```bash
cd /opt/localforge
git pull

# Actualizar dependencias Python si hay cambios
source .venv/bin/activate
pip install -r requirements.txt  # si existe

# Reconstruir frontend
cd frontend && npm install && VITE_API_BASE=/api npm run build && cd ..

# Reiniciar servicio
sudo systemctl restart localforge
```

---

## Comandos útiles

```bash
# Ver logs en tiempo real
journalctl -u localforge -f

# Reiniciar tras cambios en localforge.json
sudo systemctl restart localforge

# Ver estado
sudo systemctl status localforge

# Testear la API directamente
curl http://localhost:8000/api/health
```

---

## Seguridad recomendada en producción

1. **Firewall**: abre solo los puertos 80 y 443
   ```bash
   sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
   ```
2. **HTTPS**: usa certbot (ver paso 6)
3. **Telegram `allowed_user_ids`**: configura los IDs de usuarios permitidos en `localforge.json`
4. **Rutas del filesystem**: limita `allowed_paths` solo a lo necesario
5. **Terminal**: considera poner `"require_confirmation": true`
