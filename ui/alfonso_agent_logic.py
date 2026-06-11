import subprocess
import pyautogui
import os
import base64
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# Desactivar el fail-safe de PyAutoGUI para evitar que se detenga si el ratón se mueve a una esquina
pyautogui.FAILSAFE = False

class AlfonsoAgentLogic:
    """Encapsulates the logic for executing local system commands."""

    async def execute_command(self, data: dict) -> dict:
        command_id = data.get("id")
        action = data.get("action")
        params = data.get("params", {})

        logger.info(f"Ejecutando comando local: {action} (ID: {command_id})")
        
        try:
            result = None
            if action == "open_app":
                command = params.get("command")
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
                result = {"message": "Captura de pantalla realizada.", "image_data": img_str}
            else:
                return {"id": command_id, "status": "error", "error": f"Acción desconocida: {action}"}
            return {"id": command_id, "status": "success", "result": result}
        except Exception as e:
            logger.error(f"Error ejecutando {action}: {str(e)}")
            return {"id": command_id, "status": "error", "error": str(e)}