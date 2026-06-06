#!/usr/bin/env bash
# apply_fixes.sh — Copia todos los fixes de Fase 3 al proyecto Alfonso
# Ejecutar desde la carpeta que contiene este script:
#   bash apply_fixes.sh /ruta/a/tu/proyecto/Alfonso

set -euo pipefail

PROJECT="${1:-/home/luisd/Alfonso}"

if [ ! -d "$PROJECT" ]; then
    echo "[ERROR] Directorio de proyecto no encontrado: $PROJECT"
    echo "        Uso: bash apply_fixes.sh /ruta/al/proyecto"
    exit 1
fi

FIXES_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo " Alfonso — Aplicando Fixes Fase 3"
echo " Proyecto: $PROJECT"
echo "========================================"

copy_file() {
    local src="$1"
    local dst="$2"
    if [ -f "$FIXES_DIR/$src" ]; then
        mkdir -p "$(dirname "$PROJECT/$dst")"
        cp "$FIXES_DIR/$src" "$PROJECT/$dst"
        echo "  ✓ $dst"
    else
        echo "  ✗ FALTA en fixes: $src"
    fi
}

echo ""
echo "── Agents ────────────────────────────────"
copy_file "app/agents/chat_agent.py"       "app/agents/chat_agent.py"
copy_file "app/agents/system_agent.py"     "app/agents/system_agent.py"
copy_file "app/agents/registry.py"         "app/agents/registry.py"
copy_file "app/agents/task_planner.py"     "app/agents/task_planner.py"

echo ""
echo "── Core ──────────────────────────────────"
copy_file "app/core/intent_router.py"          "app/core/intent_router.py"
copy_file "app/core/llm_client.py"             "app/core/llm_client.py"
copy_file "app/core/planner_orchestrator.py"   "app/core/planner_orchestrator.py"

echo ""
echo "── Tools ─────────────────────────────────"
copy_file "app/tools/system_tools.py"     "app/tools/system_tools.py"
copy_file "app/tools/browser_tools.py"    "app/tools/browser_tools.py"

echo ""
echo "── API ───────────────────────────────────"
copy_file "app/api/routes.py"             "app/api/routes.py"
copy_file "app/api/routes_fase3.py"       "app/api/routes_fase3.py"
copy_file "app/main.py"                   "app/main.py"

echo ""
echo "── Prompts ───────────────────────────────"
copy_file "app/prompts/tool_system.txt"   "app/prompts/tool_system.txt"
copy_file "app/prompts/chat_system.txt"   "app/prompts/chat_system.txt"

echo ""
echo "── Scripts ───────────────────────────────"
copy_file "audio_orchestrator.py"         "audio_orchestrator.py"
copy_file "test_fase3.py"                 "test_fase3.py"
copy_file "install_fase3.sh"              "install_fase3.sh"

echo ""
echo "========================================"
echo " ✓ Todos los archivos copiados"
echo "========================================"
echo ""
echo "  Siguiente paso — instalar dependencias:"
echo "    cd $PROJECT"
echo "    bash install_fase3.sh"
echo ""
echo "  Luego reinicia el servidor:"
echo "    uvicorn app.main:app --reload"
echo ""
echo "  Y lanza los tests:"
echo "    python test_fase3.py --only intent"
echo "    python test_fase3.py --only datetime"
echo "    python test_fase3.py --only filesystem"
echo "    python test_fase3.py --only api"
echo ""
