FROM python:3.12-slim

# Instalar dependencias del sistema indispensables
RUN apt-get update && apt-get install -y \
    curl \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Descargar e instalar Caddy
RUN curl -L "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /usr/local/bin/caddy && \
    chmod +x /usr/local/bin/caddy

# Crear el usuario no-root exigido por Hugging Face (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Instalar Ollama en el espacio de usuario
RUN curl -L https://ollama.com/download/ollama-linux-amd64.tgz -o ollama.tgz && \
    tar -xzf ollama.tgz && \
    rm ollama.tgz
ENV PATH=$HOME/app:$PATH

# Copiar el código del proyecto
COPY --chown=user:user . .

# Crear entorno virtual e instalar dependencias de Python
RUN python3 -m venv venv && \
    venv/bin/pip install --no-cache-dir --upgrade pip && \
    venv/bin/pip install --no-cache-dir -r requirements.txt

# Permisos de ejecución para el script de arranque
RUN chmod +x start.sh

# Puerto requerido por Hugging Face
EXPOSE 7860

# Variables de entorno por defecto
ENV MODEL_NAME=qwen2.5:3b
ENV OLLAMA_BASE_URL=http://localhost:11434

CMD ["./start.sh"]
