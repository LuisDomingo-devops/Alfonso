import asyncio
import json
import websockets
import subprocess
import pyautogui
import os
import base64
import logging
from io import BytesIO
import ssl

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Desactivar el fail-safe de PyAutoGUI para evitar que se detenga si el ratón se mueve a una esquina
pyautogui.FAILSAFE = False

class AlfonsoAgent:
    def __init__(self, server_url="ws://localhost:8765", auth_token=None):
        self.server_url = server_url
        self.auth_token = auth_token or os.getenv("ALFONSO_AUTH_TOKEN")

    def _is_safe_command(self, command):
        """Valida que el comando no contenga caracteres de encadenamiento peligrosos."""
        # Evita inyecciones básicas como 'notepad.exe & del /f /q C:\\*'
        forbidden_chars = [';', '&', '|', '`', '$', '>', '<']
        return not any(char in command for char in forbidden_chars)

    async def execute_command(self, data):
        command_id = data.get("id")
        action = data.get("action")
        params = data.get("params", {})

        logger.info(f"Ejecutando comando: {action} (ID: {command_id})")
        
        try:
            result = None
            if action == "open_app":
                command = params.get("command")
                if not self._is_safe_command(command):
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "Comando rechazado por razones de seguridad (caracteres no permitidos)."
                    }
                
                # Usar Popen para no bloquear el agente mientras la app está abierta
                subprocess.Popen(command, shell=True)
                result = f"Aplicación '{command}' iniciada."
            
            elif action == "type_text":
                text = params.get("text", "")
                pyautogui.write(text)
                result = f"Texto escrito: {text}"
            
            elif action == "press_key":
                key = params.get("key")
                pyautogui.press(key)
                result = f"Tecla presionada: {key}"

            elif action == "move_mouse":
                x = params.get("x", 0)
                y = params.get("y", 0)
                pyautogui.moveTo(x, y)
                result = f"Ratón movido a ({x}, {y})"

            elif action == "click":
                button = params.get("button", "left")
                pyautogui.click(button=button)
                result = f"Click realizado con botón {button}"

            elif action == "screenshot":
                screenshot = pyautogui.screenshot()
                buffered = BytesIO()
                screenshot.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                result = {
                    "message": "Captura de pantalla realizada.",
                    "image_data": img_str
                }

            else:
                return {
                    "id": command_id,
                    "status": "error",
                    "error": f"Acción desconocida: {action}"
                }

            return {
                "id": command_id,
                "status": "success",
                "result": result
            }

        except Exception as e:
            logger.error(f"Error ejecutando {action}: {str(e)}")
            return {
                "id": command_id,
                "status": "error",
                "error": str(e)
            }

    async def start(self):
        logger.info(f"Conectando al servidor Alfonso en {self.server_url}...")
        while True:
            try:
                # Configuración de seguridad para WebSockets
                ssl_context = None
                if self.server_url.startswith("wss"):
                    ssl_context = ssl.create_default_context()
                    # En desarrollo con certificados auto-firmados podrías necesitar:
                    # ssl_context.check_hostname = False
                    # ssl_context.verify_mode = ssl.CERT_NONE

                headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}
                
                async with websockets.connect(
                    self.server_url, 
                    ping_interval=20, 
                    ping_timeout=20,
                    extra_headers=headers,
                    ssl=ssl_context
                ) as websocket:
                    logger.info("Conexión establecida con el servidor.")

                    async for message in websocket:
                        data = json.loads(message)
                        response = await self.execute_command(data)
                        await websocket.send(json.dumps(response))
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError):
                logger.warning("Conexión perdida o rechazada. Reintentando en 5 segundos...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error inesperado: {str(e)}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    # En un entorno real, la URL sería la IP del servidor WSL/remoto
    # Para pruebas locales, usamos localhost
    import sys
    # Prioridad: Argumento consola > Variable Entorno > Localhost
    url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ALFONSO_SERVER_URL", "ws://localhost:8765")
    token = os.getenv("ALFONSO_AUTH_TOKEN")
    
    agent = AlfonsoAgent(server_url=url, auth_token=token)
    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        logger.info("Agente detenido manualmente.")
