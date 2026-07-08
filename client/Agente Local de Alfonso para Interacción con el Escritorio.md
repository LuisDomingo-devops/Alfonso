# Agente Local de Alfonso para Interacción con el Escritorio

Este proyecto implementa un agente local ligero que permite a Alfonso (ejecutándose en un servidor o WSL) interactuar con el entorno de escritorio del usuario (PC cliente) a través de WebSockets. Esto resuelve el problema de la separación de entornos, permitiendo a Alfonso ejecutar comandos como abrir aplicaciones, simular entradas de teclado/ratón y tomar capturas de pantalla directamente en el PC del usuario.

## Componentes

1.  **`alfonso_bridge.py`**: El servidor WebSocket que se ejecuta en el entorno de Alfonso (WSL/servidor). Actúa como un puente, recibiendo intenciones del LLM y retransmitiéndolas al agente local.
2.  **`alfonso_agent.py`**: El cliente WebSocket que se ejecuta en el PC del usuario. Escucha los comandos del `alfonso_bridge.py`, los ejecuta localmente y envía las respuestas de vuelta.

## Requisitos

*   Python 3.x
*   `pip` (gestor de paquetes de Python)

## Instalación de Dependencias

### En el Servidor (donde se ejecuta `alfonso_bridge.py`)

Necesitarás instalar la librería `websockets`:

```bash
pip install websockets
```

### En el PC del Cliente (donde se ejecuta `alfonso_agent.py`)

Necesitarás instalar las librerías `websockets`, `pyautogui` y `Pillow`:

```bash
pip install websockets pyautogui Pillow
```

**Nota sobre `pyautogui`:**

*   En sistemas Linux, `pyautogui` puede requerir la instalación de algunas dependencias adicionales para funcionar correctamente, como `python3-tk`, `python3-dev`, `scrot` o `florence` (para capturas de pantalla y control de teclado/ratón). Consulta la documentación oficial de `pyautogui` para tu distribución específica si encuentras problemas.
*   `pyautogui` por defecto tiene un "fail-safe" que detiene el programa si el ratón se mueve a una de las esquinas de la pantalla. En `alfonso_agent.py` este fail-safe está desactivado (`pyautogui.FAILSAFE = False`) para evitar interrupciones inesperadas. Ten esto en cuenta al ejecutar el agente.

## Configuración y Ejecución

### 1. Iniciar el Servidor Alfonso Bridge

En tu entorno de Alfonso (WSL o servidor remoto), ejecuta el script `alfonso_bridge.py`:

```bash
python alfonso_bridge.py
```

Por defecto, el servidor escuchará en `ws://0.0.0.0:8765`. Si necesitas cambiar el puerto o la interfaz, puedes modificar el código o añadir argumentos (actualmente no implementado, pero fácil de añadir).

Verás mensajes de log indicando que el servidor ha iniciado y está esperando conexiones.

### 2. Iniciar el Agente Local de Alfonso

En el PC del cliente, ejecuta el script `alfonso_agent.py`. Necesitarás especificar la URL del servidor `alfonso_bridge.py`. Si el servidor se ejecuta en `localhost` (para pruebas en la misma máquina), puedes usar:

```bash
python alfonso_agent.py ws://localhost:8765
```

Si el servidor se ejecuta en una máquina remota o en WSL, deberás usar la dirección IP de esa máquina. Por ejemplo, si tu WSL tiene la IP `192.168.1.100`:

```bash
python alfonso_agent.py ws://192.168.1.100:8765
```

Verás mensajes de log indicando que el agente está intentando conectar y, una vez conectado, que la conexión ha sido establecida.

## Uso (Ejemplos de Comandos)

Una vez que el agente local está conectado al puente, el servidor Alfonso puede enviar comandos. Aquí hay ejemplos de cómo el servidor podría enviar comandos al agente local (estos comandos son manejados internamente por `alfonso_bridge.py` y no necesitan ser escritos manualmente por el usuario):

*   **Abrir una aplicación (ej. `gedit` en Linux, `notepad.exe` en Windows):**
    ```python
    response = await bridge.send_command("open_app", {"command": "gedit"})
    print(response)
    ```

*   **Escribir texto:**
    ```python
    response = await bridge.send_command("type_text", {"text": "Hola desde Alfonso!"})
    print(response)
    ```

*   **Mover el ratón:**
    ```python
    response = await bridge.send_command("move_mouse", {"x": 500, "y": 300})
    print(response)
    ```

*   **Hacer clic con el ratón:**
    ```python
    response = await bridge.send_command("click", {"button": "right"})
    print(response)
    ```

*   **Tomar una captura de pantalla:**
    ```python
    response = await bridge.send_command("screenshot")
    print(response)
    # La imagen codificada en base64 estará en response["result"]["image_data"]
    ```

## Consideraciones de Seguridad (Importante)

Para un entorno de producción, es **crucial** implementar medidas de seguridad adicionales:

*   **Autenticación**: Asegura que solo los agentes autorizados puedan conectarse al `alfonso_bridge.py` y viceversa. Esto podría hacerse con tokens de API o certificados.
*   **Encriptación (WSS)**: Utiliza `wss://` en lugar de `ws://` para encriptar la comunicación WebSocket, protegiendo los datos en tránsito de escuchas no autorizadas.
*   **Autorización**: Limita las acciones que el agente local puede ejecutar. Considera una lista blanca de comandos permitidos o un sistema de permisos más granular.
*   **Firewall**: Configura firewalls para restringir el acceso al puerto del `alfonso_bridge.py` solo a las IPs de los agentes locales conocidos.

## Licencia

Este proyecto se distribuye bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.
