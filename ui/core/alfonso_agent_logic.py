import subprocess
import pyautogui
import os
import base64
import logging
import asyncio
import shutil
import platform
from io import BytesIO

# Importar el gestor de registro de apps
from core.app_registry import update_app_registry, load_app_registry, get_app_path, _KNOWN_APPS

logger = logging.getLogger(__name__)

# Desactivar el fail-safe de PyAutoGUI para evitar que se detenga si el ratón se mueve a una esquina
pyautogui.FAILSAFE = False

# FIX: comprobar la plataforma real, no solo la existencia del atributo.
# `subprocess.CREATE_NO_WINDOW` puede existir como constante en algunos
# entornos sin ser funcionalmente válido fuera de Windows (p.ej. WSL con
# python compilado con soporte completo de subprocess). hasattr() por sí
# solo no es una comprobación fiable de plataforma.
_IS_WINDOWS = platform.system() == "Windows"


class AlfonsoAgentLogic:
    """Encapsulates the logic for executing local system commands."""

    def __init__(self, registry_file=".env.apps"):
        self._system = platform.system()
        self.registry_file = registry_file
        self.app_registry = {}
        
        # Cargar registro de aplicaciones al inicializar
        self._load_registry()
    
    def _load_registry(self):
        """Carga y actualiza el registro de aplicaciones."""
        logger.info("Actualizando registro de aplicaciones instaladas...")
        try:
            update_app_registry(self.registry_file)
            self.app_registry = load_app_registry(self.registry_file)
            logger.info(f"✓ Registro cargado: {len(self.app_registry)} aplicaciones disponibles")
        except Exception as e:
            logger.warning(f"No se pudo actualizar registro de apps: {e}")
            self.app_registry = {}

    def _resolve_app_path(self, app_name: str) -> str:
        """
        Resuelve la ruta completa de una aplicación.
        Prioridad:
        1. Registro de aplicaciones (.env.apps)
        2. PATH del sistema
        3. Rutas comunes en Windows
        """
        app_lower = app_name.strip().lower()

        # 0. Mapear alias (ej: 'visual-studio-code' -> 'vscode') usando _KNOWN_APPS
        target_key = app_lower
        for known_key, patterns in _KNOWN_APPS.items():
            if app_lower == known_key.lower():
                target_key = known_key
                break
            if any(p.lower() in app_lower or app_lower in p.lower() for p in patterns):
                target_key = known_key
                break
        
        # 1. Buscar en el registro de aplicaciones
        if target_key in self.app_registry:
            registered_path = self.app_registry[target_key]
            if os.path.exists(registered_path):
                logger.info(f"App '{app_name}' (mapeada a '{target_key}') encontrada en registro: {registered_path}")
                return registered_path
        
        # 2. Intentar encontrar en PATH directamente
        which_result = shutil.which(app_name)
        if which_result:
            logger.info(f"App '{app_name}' encontrada en PATH: {which_result}")
            return which_result
        
        # 3. En Windows, buscar en rutas comunes (fallback)
        if self._system == "Windows":
            firefox_paths = [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
            ]
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            ]
            edge_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            ]
            
            app_mapping = {
                "firefox": firefox_paths,
                "chrome": chrome_paths,
                "chromium": chrome_paths,
                "edge": edge_paths,
                "google-chrome": chrome_paths,
                "msedge": edge_paths,
            }
            
            if app_lower in app_mapping:
                for path in app_mapping[app_lower]:
                    if os.path.exists(path):
                        logger.info(f"App '{app_name}' encontrada en fallback: {path}")
                        return path
        
        # 4. Retornar el comando original si no se puede resolver
        logger.warning(f"No se encontró ruta completa para '{app_name}', usando nombre directo")
        return app_name

    async def execute_command(self, data: dict) -> dict:
        command_id = data.get("id")
        action = data.get("action")
        params = data.get("params", {})

        logger.info(f"Ejecutando comando local: {action} (ID: {command_id})")
        
        try:
            result = None
            if action == "open_app":
                command = params.get("command", "").strip()
                if not command:
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "No se especificó comando o aplicación"
                    }
                
                # Resolver la ruta completa de la aplicación
                resolved_command = self._resolve_app_path(command)
                
                try:
                    logger.info(f"Iniciando aplicación: {resolved_command}")
                    # Usar Popen para no bloquear mientras la app está abierta
                    # FIX: comprobar plataforma real (_IS_WINDOWS) en vez de
                    # hasattr(subprocess, 'CREATE_NO_WINDOW'), que no garantiza
                    # que estemos en Windows.
                    if _IS_WINDOWS:
                        subprocess.Popen(
                            resolved_command,
                            shell=False,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                    else:
                        subprocess.Popen(resolved_command, shell=False)
                    result = f"Aplicación '{command}' iniciada correctamente."
                except FileNotFoundError:
                    logger.error(f"Aplicación no encontrada: {resolved_command}")
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": f"Aplicación '{command}' no encontrada en el sistema"
                    }
                
            elif action == "close_app":
                app_name = params.get("command", params.get("app_name", "")).strip()
                if not app_name:
                    return {"id": command_id, "status": "error", "error": "No se especificó la aplicación a cerrar"}
                
                try:
                    if _IS_WINDOWS:
                        exec_name = app_name if app_name.lower().endswith(".exe") else f"{app_name}.exe"
                        if "explorador" in app_name.lower(): exec_name = "explorer.exe"
                        subprocess.run(["taskkill", "/F", "/IM", exec_name], check=True, capture_output=True)
                    else:
                        subprocess.run(["pkill", "-f", app_name], check=True, capture_output=True)
                    result = f"Aplicación '{app_name}' cerrada correctamente."
                except Exception as e:
                    logger.error(f"Error cerrando {app_name}: {e}")
                    return {"id": command_id, "status": "error", "error": f"No se pudo cerrar '{app_name}'"}
            
            
            elif action == "type_text":
                text = params.get("text", "")
                await asyncio.to_thread(pyautogui.write, text)
                result = f"Texto escrito: {text}"
            
            elif action == "press_key":
                key = params.get("key")
                await asyncio.to_thread(pyautogui.press, key)
                result = f"Tecla presionada: {key}"

            elif action == "move_mouse":
                x = params.get("x", 0)
                y = params.get("y", 0)
                await asyncio.to_thread(pyautogui.moveTo, x, y)
                result = f"Ratón movido a ({x}, {y})"

            elif action == "click":
                button = params.get("button", "left")
                await asyncio.to_thread(pyautogui.click, button=button)
                result = f"Click realizado con botón {button}"

            elif action == "screenshot":
                screenshot = await asyncio.to_thread(pyautogui.screenshot)
                buffered = BytesIO()
                screenshot.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                result = {"message": "Captura de pantalla realizada.", "image_data": img_str}

            elif action == "create_file":
                path = params.get("path", "")
                content = params.get("content", "")

                # Corregir alucinaciones de ruta del LLM (ej: /Users/alfonso/Desktop -> C:/Users/luisd/Desktop)
                if _IS_WINDOWS:
                    user_home = os.path.expanduser("~")
                    if "Desktop" in path or "Escritorio" in path:
                        filename = os.path.basename(path)
                        path = os.path.join(user_home, "Desktop", filename)
                    elif path.startswith("/Users/") or path.startswith("\\Users\\"):
                        # Si el LLM usa un usuario genérico, forzamos el actual
                        parts = path.split(os.sep if os.sep in path else "/")
                        if len(parts) > 3:
                            path = os.path.join(user_home, *parts[3:])

                def _write_file():
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                
                await asyncio.to_thread(_write_file)
                result = f"Archivo creado exitosamente en: {path}"

            else:
                return {"id": command_id, "status": "error", "error": f"Acción desconocida: {action}"}
            return {"id": command_id, "status": "success", "result": result}
        except Exception as e:
            logger.error(f"Error ejecutando {action}: {str(e)}")
            return {"id": command_id, "status": "error", "error": str(e)}