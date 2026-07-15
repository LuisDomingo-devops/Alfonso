# Cómo Añadir Nuevas Integraciones en Alfonso

Alfonso utiliza una arquitectura basada en **Adapters** (para comunicación externa y bases de datos) y **Tools** (que exponen capacidades al planificador y LLM). Para añadir una nueva integración, sigue estos pasos:

---

## 1. Crear el Adaptador (Capa de Infraestructura)
Crea un archivo en `app/adapters/` (ej. `app/adapters/telegram_client.py` o `app/adapters/outlook_sync.py`). Este archivo debe:
* Leer credenciales usando variables de entorno cargadas desde `app/config.py` o `.env`.
* Gestionar la conexión de red externa y abstraer la lógica cruda de la API.
* Proveer funciones sencillas y limpias que devuelvan diccionarios de Python.

---

## 2. Definir y Registrar la Herramienta (Capa de Aplicación)
Crea o modifica un módulo de herramientas en `app/tools/server/` (ej. `app/tools/server/telegram_tools.py`). 
* Implementa las funciones que serán llamadas por el orquestador/LLM.
* Cada función debe tener un buen docstring descriptivo y tipado estático claro.
* Registra las herramientas exponiendo el diccionario `TOOLS` al final del archivo:

```python
async def send_telegram_message(chat_id: str, text: str) -> dict:
    """
    Envía un mensaje de texto a un chat o contacto a través de Telegram.
    """
    # Lógica de llamada al adaptador
    ...

TOOLS = {
    "send_telegram_message": send_telegram_message,
}
```

---

## 3. Registrar Esquemas de Validación (Opcional - Recomendado)
Para robustecer las llamadas del LLM y evitar errores por argumentos inesperados, declara el esquema de validación Pydantic `ARGS_SCHEMAS` utilizando `ToolArgsModel`:

```python
from app.adapters.tool_base import ToolArgsModel

class SendTelegramMessageArgs(ToolArgsModel):
    chat_id: str
    text: str

ARGS_SCHEMAS = {
    "send_telegram_message": (SendTelegramMessageArgs, {"mensaje": "text", "contacto": "chat_id"}),
}
```
Esto habilita la coerción permisiva, permitiendo que alias como `mensaje` se mapeen automáticamente a `text`.

---

## 4. Carga Automática
El `tool_registry.py` escaneará y cargará automáticamente tu módulo de herramientas de `app/tools/server/` al iniciar la aplicación, haciéndolo disponible inmediatamente para el orquestador.
