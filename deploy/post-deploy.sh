#!/usr/bin/env bash
# =============================================================================
# Post-despliegue de LocalForge — se ejecuta tras cada despliegue de Plesk.
#
# Hace SOLO lo que hace falta según lo que haya cambiado (dependencias Python,
# frontend, o ninguno de los dos), reinicia el servicio si procede y comprueba
# que responde. Idempotente: correrlo sin cambios no hace nada salvo la
# comprobación de salud.
#
# NO depende de git. Plesk despliega COPIANDO ficheros al directorio destino —
# no hay `.git` ahí dentro — así que la detección de cambios se hace comparando
# hashes de contenido contra el último despliegue que terminó bien.
#
# Diseñado para correr como el usuario normal de la suscripción (el mismo que
# ejecuta el servicio), NO como root. El único paso que necesita privilegio es
# el reinicio del servicio, vía una regla de sudo estrecha para ese comando
# exacto — ver el bloque "Instalación" más abajo.
#
# ── Instalación (una vez) ────────────────────────────────────────────────────
#
#   1. Regla de sudo para reiniciar el servicio sin contraseña (ejecutar como
#      root; sustituye <usuario> por el usuario de sistema de la suscripción):
#
#        echo '<usuario> ALL=(root) NOPASSWD: /bin/systemctl restart localforge' \
#            > /etc/sudoers.d/localforge
#        chmod 440 /etc/sudoers.d/localforge
#        visudo -c
#
#   2. En Plesk → tu dominio → Git → Acciones de despliegue, una sola línea:
#
#        bash /var/www/vhosts/<tu-dominio>/httpdocs/deploy/post-deploy.sh
#
#   (La ruta absoluta evita depender de en qué directorio invoque Plesk el
#   script, que varía según la versión.)
#
# Requisitos previos, ya deben existir (no los gestiona este script):
#   - venv/ o .venv/ con las dependencias base instaladas
#   - .env con VITE_API_BASE y el resto de variables de entorno
#   - El proxy /api/ de nginx apuntando a 127.0.0.1:8000 (ver DEPLOY.md)
#   - El servicio systemd corriendo como este mismo usuario, no como root
# =============================================================================
set -Eeuo pipefail

PROJECT_DIR="${LOCALFORGE_DIR:-/var/www/vhosts/recursing-golick.82-165-249-46.plesk.page/httpdocs}"
SERVICE="${LOCALFORGE_SERVICE:-localforge}"
STATE="${LOCALFORGE_STATE_FILE:-$PROJECT_DIR/.deploy-state}"
HEALTH_URL="${LOCALFORGE_HEALTH_URL:-http://127.0.0.1:8000/api/health}"

log()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$*"; }
skip() { printf '  \033[0;90m·\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

trap 'die "Falló en la línea $LINENO. El despliegue NO se ha completado — revisa arriba qué paso quedó a medias."' ERR

cd "$PROJECT_DIR" || die "No existe $PROJECT_DIR"

if [[ "$(id -u)" == "0" ]]; then
    die "Este script no debe correr como root — ejecútalo como el usuario que corre el
servicio systemd (ver 'User=' en \`systemctl cat $SERVICE\`). Solo el reinicio final
necesita privilegio, y lo pide con sudo puntual. Ejecutar todo como root volvería a
dejar venv/.env con el propietario equivocado, que es justo lo que se acaba de arreglar."
fi

# ── Hashes de lo que decide cada paso ────────────────────────────────────────
hash_of() {
    # sha256 del contenido de los ficheros que existan bajo estas rutas. Vacío
    # y estable si ninguna existe. Orden determinista (sort -z).
    #
    # `find` con una ruta que NO existe (p. ej. package-lock.json en un
    # proyecto sin lockfile, o frontend/ antes del primer build) devuelve
    # código 1 aunque el resto de rutas sí existan; con `pipefail` eso mataba
    # el script entero. Se filtran antes las rutas inexistentes.
    local existing=() p
    for p in "$@"; do
        [[ -e "$p" ]] && existing+=("$p")
    done
    if [[ ${#existing[@]} -eq 0 ]]; then
        printf '' | sha256sum | cut -d' ' -f1
        return
    fi
    { find "${existing[@]}" -type f -print0 2>/dev/null \
        | sort -z \
        | xargs -0 -r sha256sum 2>/dev/null \
        | sha256sum | cut -d' ' -f1; } || true
}

REQ_HASH="$(hash_of requirements.txt)"
BACKEND_HASH="$(hash_of backend)"
PKG_HASH="$(hash_of frontend/package.json frontend/package-lock.json)"
FRONT_HASH="$(hash_of frontend/src frontend/index.html frontend/vite.config.ts \
                      frontend/tailwind.config.js frontend/postcss.config.js \
                      frontend/tsconfig.json frontend/tsconfig.app.json)"
FRONT_HASH="$(printf '%s%s' "$PKG_HASH" "$FRONT_HASH" | sha256sum | cut -d' ' -f1)"

PREV_REQ="" PREV_BACKEND="" PREV_FRONT="" PREV_PKG=""
# shellcheck source=/dev/null
[[ -f "$STATE" ]] && source "$STATE"

[[ -f "$STATE" ]] && log "Comparando con el último despliegue correcto" \
                  || log "Sin estado previo (.deploy-state) — se hace todo"

# ── Entorno Python ───────────────────────────────────────────────────────────
VENV=""
for candidate in venv .venv; do
    [[ -x "$PROJECT_DIR/$candidate/bin/python" ]] && { VENV="$PROJECT_DIR/$candidate"; break; }
done
[[ -n "$VENV" ]] || die "No encuentro el entorno virtual (ni venv/ ni .venv/ en $PROJECT_DIR)"
PY="$VENV/bin/python"
ok "Entorno virtual: $VENV"

# ── 1. Dependencias de Python ────────────────────────────────────────────────
if [[ "$REQ_HASH" != "$PREV_REQ" ]]; then
    log "requirements.txt ha cambiado — instalando"
    "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    ok "dependencias al día"
else
    skip "requirements.txt sin cambios"
fi

# ── 2. El backend tiene que importar ANTES de reiniciar ──────────────────────
# Reiniciar primero y descubrir después que no arranca deja el servicio caído
# con la versión rota. Comprobarlo antes es gratis y evita eso.
log "Comprobando que el backend importa"
"$PY" -c 'import backend.main' \
    || die "El backend no importa. NO se ha reiniciado: sigue corriendo la versión anterior."
ok "backend.main importa"

# ── 3. Frontend ──────────────────────────────────────────────────────────────
if [[ "$FRONT_HASH" != "$PREV_FRONT" ]]; then
    [[ -f .env ]] || die "No hay .env, y de ahí sale VITE_API_BASE"

    # Última definición del .env, sin comillas ni espacios alrededor. Vite NO
    # lee el .env de la raíz del proyecto (solo el de frontend/), así que hay
    # que pasarlo explícitamente como variable de entorno al build.
    read_env_var() {
        local raw
        raw="$(grep -E "^[[:space:]]*$1[[:space:]]*=" .env | tail -1 || true)"
        raw="${raw#*=}"
        raw="${raw#"${raw%%[![:space:]]*}"}"
        raw="${raw%"${raw##*[![:space:]]}"}"
        raw="${raw%\"}"; raw="${raw#\"}"
        raw="${raw%\'}"; raw="${raw#\'}"
        printf '%s' "$raw"
    }
    API_BASE="$(read_env_var VITE_API_BASE)"
    [[ -n "$API_BASE" ]] || die "Falta VITE_API_BASE en .env.
Sin ella el bundle apunta a http://localhost:8000/api y el navegador del cliente
nunca llega al backend. Añade en .env, por ejemplo:
    VITE_API_BASE=https://tu-dominio/api"

    log "El frontend ha cambiado — reconstruyendo (VITE_API_BASE=$API_BASE)"
    pushd frontend > /dev/null

    if [[ ! -d node_modules || "$PKG_HASH" != "$PREV_PKG" ]]; then
        log "Dependencias de npm desactualizadas — reinstalando"
        if [[ -f package-lock.json ]]; then npm ci --silent; else npm install --silent; fi
        ok "node_modules al día"
    else
        skip "dependencias de npm sin cambios"
    fi

    # Build a un directorio aparte y swap atómico al final: si el proceso
    # muere a mitad (en un VPS justo de RAM el OOM killer es real), nginx
    # sigue sirviendo el dist anterior en vez de uno a medio escribir.
    # `npm run build -- --outDir dist.new` conserva el paso `tsc -b` del
    # script real (no solo `vite build`), así que también hace typecheck.
    rm -rf dist.new
    VITE_API_BASE="$API_BASE" npm run build -- --outDir dist.new
    rm -rf dist.old
    [[ -d dist ]] && mv dist dist.old
    mv dist.new dist
    rm -rf dist.old

    popd > /dev/null
    ok "frontend reconstruido"
else
    skip "frontend sin cambios, no se reconstruye"
fi

# ── 4. Reiniciar (solo si backend o requirements cambiaron) ─────────────────
if [[ "$BACKEND_HASH" != "$PREV_BACKEND" || "$REQ_HASH" != "$PREV_REQ" ]]; then
    log "Reiniciando $SERVICE"
    sudo -n systemctl restart "$SERVICE" || die "No se pudo reiniciar $SERVICE con sudo.
Comprueba que existe /etc/sudoers.d/localforge con la regla NOPASSWD para
'systemctl restart $SERVICE' — ver la cabecera de este fichero."
    ok "servicio reiniciado"
else
    skip "backend sin cambios, no hace falta reiniciar"
fi

# ── 5. Comprobar que responde ────────────────────────────────────────────────
log "Comprobando la salud del servicio"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
for _ in $(seq 1 20); do
    if curl -fsS --max-time 3 "$HEALTH_URL" -o "$TMP" 2>/dev/null; then
        ok "$(cat "$TMP")"
        # El estado solo se guarda si TODO salió bien: si algo falló antes, el
        # siguiente despliegue reintenta los pasos que quedaron pendientes.
        cat > "$STATE" <<EOF
PREV_REQ="$REQ_HASH"
PREV_BACKEND="$BACKEND_HASH"
PREV_FRONT="$FRONT_HASH"
PREV_PKG="$PKG_HASH"
EOF
        printf '\n\033[0;32m✓ Despliegue completo\033[0m\n\n'
        exit 0
    fi
    sleep 1
done
die "El servicio no responde en $HEALTH_URL tras 20s.
Mira qué pasó:  journalctl -u $SERVICE -n 50 --no-pager"
