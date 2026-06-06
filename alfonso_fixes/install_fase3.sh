#!/usr/bin/env bash
# install_fase3.sh — Instala dependencias de Fase 3 en el entorno virtual de Alfonso
# Ejecutar desde la raíz del proyecto: bash install_fase3.sh

set -euo pipefail

VENV_PIP="venv/bin/pip"
if [ ! -f "$VENV_PIP" ]; then
    echo "[ERROR] No se encontró el entorno virtual en ./venv"
    echo "        Crea el venv primero: python3 -m venv venv && source venv/bin/activate"
    exit 1
fi

echo "========================================"
echo " Alfonso — Instalación de Fase 3"
echo "========================================"

# ── Playwright (navegador) ────────────────────────────────────────────────
echo ""
echo "[1/5] Instalando Playwright..."
"$VENV_PIP" install playwright --quiet
venv/bin/playwright install chromium
echo "      ✓ Playwright + Chromium instalados"

# ── PyAutoGUI (ratón/teclado) ─────────────────────────────────────────────
echo ""
echo "[2/5] Instalando PyAutoGUI..."
"$VENV_PIP" install pyautogui --quiet
echo "      ✓ PyAutoGUI instalado"

# ── OCR (Tesseract + pytesseract) ─────────────────────────────────────────
echo ""
echo "[3/5] Instalando pytesseract + Pillow..."
"$VENV_PIP" install pytesseract Pillow --quiet

# Intentar instalar tesseract-ocr del sistema si no está
if ! command -v tesseract &>/dev/null; then
    echo "      Instalando tesseract-ocr del sistema..."
    sudo apt-get install -y tesseract-ocr tesseract-ocr-spa 2>/dev/null || \
        echo "      [AVISO] No se pudo instalar tesseract automáticamente. Instálalo con: sudo apt install tesseract-ocr"
else
    echo "      ✓ tesseract ya instalado: $(tesseract --version 2>&1 | head -1)"
fi
echo "      ✓ pytesseract instalado"

# ── OpenCV (template matching) ────────────────────────────────────────────
echo ""
echo "[4/5] Instalando OpenCV..."
"$VENV_PIP" install opencv-python-headless --quiet
echo "      ✓ OpenCV instalado"

# ── psutil (ya debería estar, pero aseguramos) ────────────────────────────
echo ""
echo "[5/5] Verificando psutil..."
"$VENV_PIP" install psutil --quiet
echo "      ✓ psutil OK"

# ── wmctrl (control de ventanas en Linux) ─────────────────────────────────
echo ""
echo "[EXTRA] Comprobando wmctrl (control de ventanas)..."
if ! command -v wmctrl &>/dev/null; then
    sudo apt-get install -y wmctrl 2>/dev/null || \
        echo "      [AVISO] wmctrl no instalado. Instálalo con: sudo apt install wmctrl"
else
    echo "      ✓ wmctrl ya instalado"
fi

# ── Variables de entorno para WSL ─────────────────────────────────────────
echo ""
echo "========================================"
echo " Configuración WSL (si aplica)"
echo "========================================"
echo ""
echo "  Para usar PyAutoGUI en WSL necesitas un servidor X:"
echo "    export DISPLAY=:0"
echo "    export XAUTHORITY=\$HOME/.Xauthority"
echo ""
echo "  Para ver el navegador en pantalla (no headless):"
echo "    export ALFONSO_HEADLESS=false"
echo ""
echo "  Para usar Firefox en lugar de Chromium:"
echo "    export ALFONSO_BROWSER=firefox"
echo "    venv/bin/playwright install firefox"
echo ""

echo "========================================"
echo " ✓ Instalación Fase 3 completada"
echo "========================================"
echo ""
echo "  Reinicia el servidor:"
echo "    uvicorn app.main:app --reload"
echo ""
