#!/bin/bash
# start.sh — Inicia Ollama, descarga el modelo, arranca FastAPI y levanta Caddy

set -e

echo "=== Iniciando Ollama en segundo plano ==="
export OLLAMA_HOST=127.0.0.1:11434
ollama serve > ollama.log 2>&1 &

# Esperar a que Ollama esté listo
echo "Esperando a que Ollama responda..."
for i in {1..30}; do
  if curl -s http://127.0.0.1:11434 > /dev/null; then
    echo "Ollama está listo."
    break
  fi
  sleep 1
done

# Descargar el modelo configurado (por defecto qwen2.5:3b)
MODEL=${MODEL_NAME:-"qwen2.5:3b"}
echo "Descargando modelo $MODEL..."
ollama pull $MODEL

echo "=== Iniciando servidor Alfonso en puerto local 8000 ==="
# El servidor corre en local 8000; Caddy lo expondrá al exterior en el 7860
venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > fastapi.log 2>&1 &

echo "=== Iniciando Caddy como proxy inverso (Puerto 7860) ==="
# Caddy recibe todo en 7860 y lo reparte entre FastAPI (8000) y Websockets (8765)
exec caddy run --config Caddyfile --adapter caddyfile
