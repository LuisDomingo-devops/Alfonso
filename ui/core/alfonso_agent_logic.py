import subprocess
import pyautogui
import os
import base64
import logging
import asyncio
import shutil
import platform
from io import BytesIO
import webbrowser

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

    def _resolve_local_path(self, raw_path: str) -> str:
        if not raw_path:
            return raw_path
        
        # 1. Normalizar barras
        path = raw_path.replace("\\", "/")
        
        # 2. Si estamos en Windows, traducir rutas de WSL (/mnt/<drive>/...)
        if self._system == "Windows":
            import re
            # Traducir /mnt/c/... a C:\...
            mnt_match = re.match(r"^/mnt/([a-zA-Z])(.*)$", path)
            if mnt_match:
                drive = mnt_match.group(1).upper()
                remainder = mnt_match.group(2).replace("/", "\\")
                path = f"{drive}:{remainder}"
                logger.info(f"Ruta de WSL detectada en Windows. Corrigiendo a: {path}")
            
            # Traducir /home/<user>/... a \\wsl.localhost\Ubuntu\home\<user>\...
            home_match = re.match(r"^/home/([^/]+)(.*)$", path)
            if home_match:
                user = home_match.group(1)
                remainder = home_match.group(2).replace("/", "\\")
                path = f"\\\\wsl.localhost\\Ubuntu\\home\\{user}{remainder}"
                logger.info(f"Ruta de home de WSL detectada en Windows. Corrigiendo a UNC: {path}")

        # 3. Mapear rutas absolutas de macOS o de otros usuarios al home del usuario local
        import re
        match = re.match(r"^(?:/Users/[^/]+|C:/Users/[^/]+)(/.*)$", path, re.IGNORECASE)
        if match:
            remainder = match.group(1).lstrip("/")
            home = os.path.expanduser("~")
            path = os.path.join(home, remainder)

        # 4. Expandir ~ o ~/ a HOME del usuario local
        if path.startswith("~/"):
            home = os.path.expanduser("~")
            path = path.replace("~/", home + "/")
        elif path.startswith("~"):
            home = os.path.expanduser("~")
            path = home + path[1:]

        # 5. Redireccionar Desktop/Escritorio al directorio real de Desktop
        parts = path.split("/")
        if len(parts) > 1:
            for idx, part in enumerate(parts):
                if part.lower() in ["desktop", "escritorio"]:
                    home = os.path.expanduser("~")
                    desktop_dir = os.path.join(home, "Desktop")
                    if not os.path.exists(desktop_dir):
                        desktop_dir = os.path.join(home, "Escritorio")
                    remainder = "/".join(parts[idx+1:])
                    path = os.path.join(desktop_dir, remainder)
                    break

        return os.path.normpath(path)

    def _resolve_app_path(self, app_name: str) -> str:
        """
        Resuelve la ruta completa de una aplicación.
        Prioridad:
        1. Registro de aplicaciones (.env.apps)
        2. PATH del sistema
        3. Rutas comunes en Windows
        """
        app_lower = app_name.strip().lower()

        # Mapear comandos específicos de Linux a Windows si es aplicable
        if self._system == "Windows":
            if "nautilus" in app_lower:
                logger.info(f"Mapeando nautilus a explorer.exe en Windows")
                return "explorer.exe"
            if app_lower.endswith("/code") or app_lower == "code":
                return "code"

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
        raw_action = data.get("action")
        params = data.get("params", {})

        action_mapping = {
            "open_url": "open_url",
            "system.open_url": "open_url",
            "open_app": "open_app",
            "system.open_app": "open_app",
            "close_app": "close_app",
            "system.close_app": "close_app",
            
            "keyboard.type": "type_text",
            "type_text": "type_text",
            "keyboard.press": "press_key",
            "press_key": "press_key",
            "keyboard.hotkey": "press_hotkey",
            
            "mouse.move": "move_mouse",
            "move_mouse": "move_mouse",
            "mouse.click": "click",
            "click": "click",
            "mouse.drag": "drag_mouse",
            
            "screen.screenshot": "screenshot",
            "screenshot": "screenshot",
            "screen.ocr_screenshot": "ocr_screenshot",
            "screen.ocr_image": "ocr_image",
            "screen.find_on_screen": "find_on_screen",
            
            "window.list": "window_list",
            "window.focus": "window_focus",
            "window.close": "window_close",
            
            # Filesystem
            "create_file": "create_file",
            "read_file": "read_file",
            "list_directory": "list_directory",
            "create_directory": "create_directory",
            "append_file": "append_file",
            "delete_file": "delete_file",
            "delete_directory": "delete_directory",
            "move_file": "move_file",
            "rename_file": "rename_file",
        }

        action = action_mapping.get(raw_action, raw_action)
        logger.info(f"Ejecutando comando local: {action} (raw: {raw_action}, ID: {command_id})")
        
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
                    if _IS_WINDOWS:
                        # Para comandos nativos del shell de Windows como explorer.exe o code, usar shell=True es más seguro y previene FileNotFoundError
                        use_shell = resolved_command.lower() in ["explorer.exe", "code"] or not resolved_command.endswith(".exe")
                        subprocess.Popen(
                            resolved_command,
                            shell=use_shell,
                            creationflags=subprocess.CREATE_NO_WINDOW if not use_shell else 0
                        )
                    else:
                        subprocess.Popen(resolved_command, shell=False)
                    result = f"Aplicación '{command}' iniciada correctamente."
                except FileNotFoundError:
                    try:
                        # Fallback for Windows using shell=True
                        if _IS_WINDOWS:
                            subprocess.Popen(resolved_command, shell=True)
                            result = f"Aplicación '{command}' iniciada (shell fallback)."
                        else:
                            raise
                    except Exception as e:
                        logger.error(f"Aplicación no encontrada: {resolved_command} — {e}")
                        return {
                            "id": command_id,
                            "status": "error",
                            "error": f"Aplicación '{command}' no encontrada en el sistema: {e}"
                        }
                
            elif action == "close_app":
                app_name = params.get("command", params.get("app_name", "")).strip()
                if not app_name:
                    return {"id": command_id, "status": "error", "error": "No se especificó la aplicación a cerrar"}
                
                try:
                    if _IS_WINDOWS:
                        exec_name = app_name if app_name.lower().endswith(".exe") else f"{app_name}.exe"
                        if exec_name.lower() == "explorer.exe" or "explorador" in app_name.lower():
                            logger.warning("Evitando taskkill en explorer.exe para no tumbar la shell de Windows. Usando Alt+F4.")
                            pyautogui.hotkey("alt", "f4")
                            result = "Se envió Alt+F4 a la ventana activa."
                        else:
                            subprocess.run(["taskkill", "/F", "/IM", exec_name], check=True, capture_output=True)
                            result = f"Aplicación '{app_name}' cerrada correctamente."
                    else:
                        subprocess.run(["pkill", "-f", app_name], check=True, capture_output=True)
                        result = f"Aplicación '{app_name}' cerrada correctamente."
                except Exception as e:
                    logger.error(f"Error cerrando {app_name}: {e}")
                    return {"id": command_id, "status": "error", "error": f"No se pudo cerrar '{app_name}'"}
            
            elif action == "open_url":
                url = params.get("url", "").strip()
                if not url:
                    return {"id": command_id, "status": "error", "error": "URL vacía"}
                if _IS_WINDOWS:
                    try:
                        subprocess.Popen(["explorer.exe", url], shell=False)
                    except Exception as e:
                        logger.error(f"Error con subprocess.Popen explorer.exe: {e}")
                        try:
                            os.startfile(url)
                        except Exception as ex:
                            logger.error(f"Error con os.startfile: {ex}")
                            asyncio.create_task(asyncio.to_thread(webbrowser.open, url))
                else:
                    asyncio.create_task(asyncio.to_thread(webbrowser.open, url))
                result = f"URL abierta: {url}"

            elif action == "type_text":
                text = params.get("text", "")
                await asyncio.to_thread(pyautogui.write, text)
                result = f"Texto escrito: {text}"
            
            elif action == "press_key":
                key = params.get("key")
                await asyncio.to_thread(pyautogui.press, key)
                result = f"Tecla presionada: {key}"

            elif action == "press_hotkey":
                keys = params.get("keys", [])
                if not keys:
                    return {"id": command_id, "status": "error", "error": "keys vacío"}
                await asyncio.to_thread(pyautogui.hotkey, *keys)
                result = f"Hotkey presionada: {keys}"

            elif action == "move_mouse":
                x = params.get("x", 0)
                y = params.get("y", 0)
                await asyncio.to_thread(pyautogui.moveTo, x, y)
                result = f"Ratón movido a ({x}, {y})"

            elif action == "click":
                button = params.get("button", "left")
                await asyncio.to_thread(pyautogui.click, button=button)
                result = f"Click realizado con botón {button}"

            elif action == "drag_mouse":
                x2 = params.get("x2", 0)
                y2 = params.get("y2", 0)
                button = params.get("button", "left")
                duration = params.get("duration", 0.5)
                await asyncio.to_thread(pyautogui.dragTo, x2, y2, button=button, duration=duration)
                result = f"Arrastre realizado a ({x2}, {y2})"

            elif action == "screenshot":
                screenshot = await asyncio.to_thread(pyautogui.screenshot)
                buffered = BytesIO()
                screenshot.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                result = {"message": "Captura de pantalla realizada.", "image_data": img_str}

            elif action == "ocr_screenshot" or action == "ocr_image":
                result = {"text": "Texto simulado OCR"}

            elif action == "find_on_screen":
                result = {"x": 100, "y": 100}

            elif action == "window_list":
                result = {"windows": [{"title": "Alfonso GUI", "id": 1}]}

            elif action == "window_focus":
                result = "focused"

            elif action == "window_close":
                result = "closed"

            elif action == "create_file":
                path = self._resolve_local_path(params.get("path", ""))
                content = params.get("content", "")
                def _write_file():
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                await asyncio.to_thread(_write_file)
                result = f"Archivo creado exitosamente en: {path}"

            elif action == "read_file":
                path = self._resolve_local_path(params.get("path", ""))
                def _read_file():
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                result = await asyncio.to_thread(_read_file)

            elif action == "list_directory":
                path = self._resolve_local_path(params.get("path", "."))
                result = await asyncio.to_thread(os.listdir, path)

            elif action == "create_directory":
                path = self._resolve_local_path(params.get("path", ""))
                await asyncio.to_thread(os.makedirs, path, exist_ok=True)
                result = f"Directorio creado: {path}"

            elif action == "append_file":
                path = self._resolve_local_path(params.get("path", ""))
                content = params.get("content", "")
                def _append_file():
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(content)
                await asyncio.to_thread(_append_file)
                result = f"Contenido añadido al archivo: {path}"

            elif action == "delete_file":
                path = self._resolve_local_path(params.get("path", ""))
                await asyncio.to_thread(os.remove, path)
                result = f"Archivo eliminado: {path}"

            elif action == "delete_directory":
                path = self._resolve_local_path(params.get("path", ""))
                await asyncio.to_thread(shutil.rmtree, path)
                result = f"Directorio eliminado: {path}"

            elif action == "move_file":
                src = self._resolve_local_path(params.get("old_path") or params.get("src", ""))
                dst = self._resolve_local_path(params.get("new_path") or params.get("dst", ""))
                await asyncio.to_thread(shutil.move, src, dst)
                result = f"Archivo movido de {src} a {dst}"

            elif action == "rename_file":
                src = self._resolve_local_path(params.get("path") or params.get("src", ""))
                dst = params.get("new_name") or params.get("dst", "")
                if not os.path.isabs(dst) and not dst.startswith(".") and "/" not in dst and "\\" not in dst:
                    dst = os.path.join(os.path.dirname(src), dst)
                else:
                    dst = self._resolve_local_path(dst)
                await asyncio.to_thread(os.rename, src, dst)
                result = f"Archivo renombrado de {src} a {dst}"

            else:
                return {"id": command_id, "status": "error", "error": f"Acción desconocida: {action}"}
            return {"id": command_id, "status": "success", "result": result}
        except Exception as e:
            logger.error(f"Error ejecutando {action}: {str(e)}")
            return {"id": command_id, "status": "error", "error": str(e)}