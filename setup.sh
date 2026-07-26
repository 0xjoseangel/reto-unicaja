#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Habla con tu dinero — Setup interactivo
#  Configura el proveedor de IA y arranca el proyecto con Docker
# ══════════════════════════════════════════════════════════════════════════════
set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

header() { echo -e "\n${BOLD}${CYAN}$1${RESET}"; }
ok()     { echo -e "${GREEN}✓${RESET} $1"; }
warn()   { echo -e "${YELLOW}⚠${RESET}  $1"; }
err()    { echo -e "${RED}✗${RESET} $1"; exit 1; }

# ── Requisitos ────────────────────────────────────────────────────────────────
header "Comprobando requisitos..."
command -v docker &>/dev/null || err "Docker no está instalado. Visita https://docs.docker.com/get-docker/"
docker info &>/dev/null       || err "Docker no está corriendo. Arráncalo e inténtalo de nuevo."
ok "Docker disponible"

# ── Aviso si ya existe .env ───────────────────────────────────────────────────
ENV_FILE="backend/.env"
if [ -f "$ENV_FILE" ]; then
    warn "Ya existe un fichero $ENV_FILE."
    read -rp "  ¿Sobreescribir? [s/N]: " OVERWRITE
    [[ "$OVERWRITE" =~ ^[sS]$ ]] || { echo "Saliendo sin cambios."; exit 0; }
fi

# ── Elegir proveedor ──────────────────────────────────────────────────────────
header "¿Qué proveedor de IA quieres usar?"
echo -e "  ${BOLD}1)${RESET} Anthropic — Claude  ${YELLOW}(alta calidad, de pago)${RESET}"
echo -e "  ${BOLD}2)${RESET} OpenAI    — GPT     ${YELLOW}(muy capaz, de pago)${RESET}"
echo -e "  ${BOLD}3)${RESET} Groq      — Llama   ${GREEN}(ultra-rápido, tier gratuito)${RESET}"
echo -e "  ${BOLD}4)${RESET} Google    — Gemini  ${YELLOW}(tier gratuito disponible)${RESET}"
echo -e "  ${BOLD}5)${RESET} Mistral             ${YELLOW}(de pago, buena relación calidad/precio)${RESET}"
echo -e "  ${BOLD}6)${RESET} Ollama    — Local   ${GREEN}(gratis, privado, sin internet)${RESET}"
echo ""
read -rp "Elige [1-6]: " PROVIDER_CHOICE

LITELLM_API_BASE_LINE=""
API_KEY_LINE=""

case "$PROVIDER_CHOICE" in
1)  # Anthropic
    header "Modelos de Claude disponibles:"
    echo "  1) claude-haiku-4-5   — Rápido y barato (recomendado para desarrollo)"
    echo "  2) claude-sonnet-4-6  — Equilibrado calidad/velocidad"
    echo "  3) claude-opus-4-8    — Máxima calidad"
    read -rp "Modelo [1-3, default 1]: " M
    case "$M" in
        2) MODEL="claude-sonnet-4-6" ;;
        3) MODEL="claude-opus-4-8" ;;
        *) MODEL="claude-haiku-4-5" ;;
    esac
    LITELLM_MODEL="anthropic/$MODEL"
    echo ""
    echo "Obtén tu API key en: https://console.anthropic.com"
    read -rp "ANTHROPIC_API_KEY: " API_KEY
    [ -z "$API_KEY" ] && err "La API key no puede estar vacía."
    API_KEY_LINE="ANTHROPIC_API_KEY=$API_KEY"
    ;;

2)  # OpenAI
    header "Modelos de OpenAI disponibles:"
    echo "  1) gpt-4o-mini — Rápido y barato (recomendado)"
    echo "  2) gpt-4o      — Máxima calidad"
    read -rp "Modelo [1-2, default 1]: " M
    case "$M" in
        2) MODEL="gpt-4o" ;;
        *) MODEL="gpt-4o-mini" ;;
    esac
    LITELLM_MODEL="openai/$MODEL"
    echo ""
    echo "Obtén tu API key en: https://platform.openai.com/api-keys"
    read -rp "OPENAI_API_KEY: " API_KEY
    [ -z "$API_KEY" ] && err "La API key no puede estar vacía."
    API_KEY_LINE="OPENAI_API_KEY=$API_KEY"
    ;;

3)  # Groq
    header "Modelos de Groq disponibles:"
    echo "  1) llama-3.3-70b-versatile  — Mejor calidad (recomendado)"
    echo "  2) llama-3.1-8b-instant     — Ultra-rápido"
    echo "  3) gemma2-9b-it             — Alternativa ligera"
    read -rp "Modelo [1-3, default 1]: " M
    case "$M" in
        2) MODEL="llama-3.1-8b-instant" ;;
        3) MODEL="gemma2-9b-it" ;;
        *) MODEL="llama-3.3-70b-versatile" ;;
    esac
    LITELLM_MODEL="groq/$MODEL"
    echo ""
    echo "Obtén tu API key gratuita en: https://console.groq.com"
    read -rp "GROQ_API_KEY: " API_KEY
    [ -z "$API_KEY" ] && err "La API key no puede estar vacía."
    API_KEY_LINE="GROQ_API_KEY=$API_KEY"
    ;;

4)  # Gemini
    header "Modelos de Gemini disponibles:"
    echo "  1) gemini-2.0-flash — Rápido, tier gratuito (recomendado)"
    echo "  2) gemini-1.5-pro   — Mayor contexto y calidad"
    read -rp "Modelo [1-2, default 1]: " M
    case "$M" in
        2) MODEL="gemini-1.5-pro" ;;
        *) MODEL="gemini-2.0-flash" ;;
    esac
    LITELLM_MODEL="gemini/$MODEL"
    echo ""
    echo "Obtén tu API key gratuita en: https://aistudio.google.com/apikey"
    read -rp "GEMINI_API_KEY: " API_KEY
    [ -z "$API_KEY" ] && err "La API key no puede estar vacía."
    API_KEY_LINE="GEMINI_API_KEY=$API_KEY"
    ;;

5)  # Mistral
    header "Modelos de Mistral disponibles:"
    echo "  1) mistral-small-latest — Rápido y eficiente (recomendado)"
    echo "  2) mistral-large-latest — Máxima calidad"
    read -rp "Modelo [1-2, default 1]: " M
    case "$M" in
        2) MODEL="mistral-large-latest" ;;
        *) MODEL="mistral-small-latest" ;;
    esac
    LITELLM_MODEL="mistral/$MODEL"
    echo ""
    echo "Obtén tu API key en: https://console.mistral.ai"
    read -rp "MISTRAL_API_KEY: " API_KEY
    [ -z "$API_KEY" ] && err "La API key no puede estar vacía."
    API_KEY_LINE="MISTRAL_API_KEY=$API_KEY"
    ;;

6)  # Ollama local
    header "Modelos de Ollama disponibles (se descargan automáticamente):"
    echo "  1) llama3.2        — Meta Llama 3.2 3B  (~2 GB)"
    echo "  2) qwen2.5:7b      — Alibaba Qwen 2.5 7B (~5 GB, muy bueno en español)"
    echo "  3) gemma3          — Google Gemma 3 4B   (~3 GB)"
    echo "  4) mistral         — Mistral 7B          (~4 GB)"
    echo "  5) phi4            — Microsoft Phi-4     (~9 GB)"
    echo "  6) Otro (escribe el nombre de ollama.com)"
    read -rp "Modelo [1-6, default 2]: " M
    case "$M" in
        1) OLLAMA_MODEL="llama3.2" ;;
        3) OLLAMA_MODEL="gemma3" ;;
        4) OLLAMA_MODEL="mistral" ;;
        5) OLLAMA_MODEL="phi4" ;;
        6) read -rp "Nombre del modelo: " OLLAMA_MODEL ;;
        *) OLLAMA_MODEL="qwen2.5:7b" ;;
    esac
    LITELLM_MODEL="ollama/$OLLAMA_MODEL"
    LITELLM_API_BASE_LINE="LITELLM_API_BASE=http://ollama:11434"

    echo ""
    read -rp "¿Tienes GPU NVIDIA disponible? [s/N]: " HAS_GPU
    USE_GPU=false
    [[ "$HAS_GPU" =~ ^[sS]$ ]] && USE_GPU=true
    ;;

*)  err "Opción no válida." ;;
esac

# ── Escribir .env ─────────────────────────────────────────────────────────────
header "Escribiendo configuración en $ENV_FILE..."

cat > "$ENV_FILE" << EOF
# Generado por setup.sh — $(date)
LITELLM_MODEL=$LITELLM_MODEL
$API_KEY_LINE
$LITELLM_API_BASE_LINE
DATABASE_URL=sqlite:////app/data/db.sqlite3
MODEL_CACHE_DIR=/app/models
EOF

ok "Fichero $ENV_FILE creado"

# ── Arrancar Docker ───────────────────────────────────────────────────────────
header "Arrancando servicios Docker..."

if [ "$PROVIDER_CHOICE" = "6" ]; then
    docker compose --profile ollama up -d --build
else
    docker compose up -d --build
fi

# ── Esperar a que el backend esté listo ───────────────────────────────────────
header "Esperando a que el backend esté listo..."
MAX_WAIT=60
WAITED=0
until curl -sf http://localhost:8000/ > /dev/null 2>&1; do
    sleep 2
    WAITED=$((WAITED + 2))
    [ $WAITED -ge $MAX_WAIT ] && err "El backend no arrancó en ${MAX_WAIT}s. Revisa: docker compose logs backend"
    echo -n "."
done
echo ""
ok "Backend listo"

# ── Descargar modelo Ollama si procede ────────────────────────────────────────
if [ "$PROVIDER_CHOICE" = "6" ]; then
    header "Descargando modelo $OLLAMA_MODEL con Ollama..."
    warn "Esto puede tardar varios minutos según el modelo y tu conexión."
    docker exec reto-unicaja-ollama-1 ollama pull "$OLLAMA_MODEL" 2>&1 || \
    docker exec "$(docker compose ps -q ollama)" ollama pull "$OLLAMA_MODEL"
    ok "Modelo $OLLAMA_MODEL descargado"
fi

# ── Seed de la base de datos si es primera vez ────────────────────────────────
BACKEND_CTR=$(docker compose ps -q backend)
DB_EXISTS=$(docker exec "$BACKEND_CTR" test -f /app/data/db.sqlite3 && echo "yes" || echo "no")
if [ "$DB_EXISTS" = "no" ]; then
    header "Inicializando base de datos con datos de ejemplo..."
    docker exec "$BACKEND_CTR" python seed.py
    ok "Base de datos inicializada"
fi

# ── Listo ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  ¡Todo listo!${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════${RESET}"
echo ""
echo -e "  Proveedor: ${BOLD}$LITELLM_MODEL${RESET}"
echo -e "  Frontend:  ${CYAN}http://localhost:3000${RESET}"
echo -e "  API docs:  ${CYAN}http://localhost:8000/docs${RESET}"
echo ""
echo -e "  Para parar:    ${BOLD}docker compose down${RESET}"
echo -e "  Para los logs: ${BOLD}docker compose logs -f backend${RESET}"
echo ""
