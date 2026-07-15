#!/bin/bash
# deploy.sh — Script de despliegue automatizado para CI/CD

set -e

echo "=== Iniciando despliegue de Alfonso ==="

# 1. Ir al directorio de la aplicación
cd /home/ubuntu/alfonso

# 2. Traer los últimos cambios de Git
echo "Actualizando código desde Git..."
git pull origin main

# 3. Activar entorno virtual e instalar dependencias
echo "Instalando dependencias..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Reiniciar el servicio en systemd
echo "Reiniciando el servicio Alfonso..."
sudo systemctl restart alfonso

echo "=== Despliegue completado con éxito ==="
