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
import shutil
import platform
from pathlib import Path

# Importar el gestor de registro de apps
from core.app_registry import update_app_registry, load_app_registry, get_app_path

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Desactivar el fail-safe de PyAutoGUI para evitar que se detenga si el ratón se mueve a una esquina
pyautogui.FAILSAFE = False

# FIX: comprobar la plataforma real en vez de hasattr(subprocess, 'CREATE_NO_WINDOW').
# hasattr no garantiza que el flag sea funcionalmente válido fuera de Windows.
_IS_WINDOWS = platform.system() == "Windows"


class AlfonsoAgent:
    def __init__(self, server_url="ws://localhost:8765", auth_token=None, registry_file=".env.apps"):
        self.server_url = server_url
        self.auth_token = auth_token or os.getenv("ALFONSO_AUTH_TOKEN")
        self._system = platform.system()
        self.registry_file = registry_file
        self.app_registry = {}  # Será cargado en start()

    def _resolve_app_path(self, app_name: str) -> str:
        """
        Resuelve la ruta completa de una aplicación.
        Prioridad:
        1. Registro de aplicaciones (.env.apps)
        2. PATH del sistema
        3. Rutas comunes en Windows
        """
        app_lower = app_name.strip().lower()
        
        # 1. Buscar en el registro de aplicaciones
        if app_lower in self.app_registry:
            registered_path = self.app_registry[app_lower]
            if os.path.exists(registered_path):
                logger.info(f"App '{app_name}' encontrada en registro: {registered_path}")
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
    @staticmethod
    def _require(module_name: str):
        import importlib
        try:
            return importlib.import_module(module_name)
        except ImportError:
            raise RuntimeError(
                f"Módulo '{module_name}' no instalado en el agente local. "
                f"Ejecuta: pip install {module_name}"
            )
    def _close_file_explorer_windows() -> dict:
        """
        Cierra únicamente las VENTANAS de File Explorer (clase CabinetWClass),
        NUNCA el proceso explorer.exe — eso mataría el shell de Windows
        (barra de tareas, escritorio) y dejaría al usuario sin desktop.
        """
        import pygetwindow as gw
        closed = []
        for w in gw.getAllWindows():
            # File Explorer expone su título como el nombre de la carpeta;
            # filtramos por clase real de ventana, no por título, para evitar
            # falsos positivos con otras apps que contengan "explorador" en el título.
            try:
                import win32gui
                class_name = win32gui.GetClassName(w._hWnd)
            except Exception:
                class_name = None
            if class_name == "CabinetWClass":
                w.close()
                closed.append(w.title)
        if closed:
            return {"status": "ok", "message": f"Cerradas {len(closed)} ventanas de Explorer", "windows": closed}
        return {"status": "error", "message": "No hay ventanas de Explorer abiertas"}

    def _get_window_titles(self) -> list:
        if self._system == "Windows":
            import pygetwindow as gw
            return [w.title for w in gw.getAllWindows() if w.title.strip()]
        out = subprocess.check_output(["wmctrl", "-l"], text=True)
        return [p[3] for line in out.splitlines() if len(p := line.split(None, 3)) == 4]

    def _focus_window(self, title: str) -> dict:
        if self._system == "Windows":
            import pygetwindow as gw
            wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
            if not wins:
                return {"status": "error", "message": f"Ventana no encontrada: {title}"}
            wins[0].activate()
            return {"status": "ok", "title": wins[0].title}
        out = subprocess.check_output(["wmctrl", "-l"], text=True)
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and title.lower() in parts[3].lower():
                subprocess.run(["wmctrl", "-ia", parts[0]], check=True)
                return {"status": "ok", "title": parts[3], "wid": parts[0]}
        return {"status": "error", "message": f"Ventana no encontrada: {title}"}

    def _close_window(self, title: str) -> dict:
        if self._system == "Windows":
            import pygetwindow as gw
            wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
            if not wins:
                return {"status": "error", "message": f"Ventana no encontrada: {title}"}
            wins[0].close()
            return {"status": "ok", "title": wins[0].title}
        out = subprocess.check_output(["wmctrl", "-l"], text=True)
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and title.lower() in parts[3].lower():
                subprocess.run(["wmctrl", "-ic", parts[0]], check=True)
                return {"status": "ok", "title": parts[3], "wid": parts[0]}
        return {"status": "error", "message": f"Ventana no encontrada: {title}"}
    
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
                command = params.get("command", "").strip()
                if not command:
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "No se especificó comando o aplicación"
                    }
                    
                if not self._is_safe_command(command):
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "Comando rechazado por razones de seguridad (caracteres no permitidos)."
                    }
                
                # Resolver la ruta completa de la aplicación
                resolved_command = self._resolve_app_path(command)
                
                try:
                    logger.info(f"Iniciando aplicación: {resolved_command}")
                    # Usar Popen para no bloquear el agente mientras la app está abierta
                    # FIX: comprobar plataforma real (_IS_WINDOWS) en vez de
                    # hasattr(subprocess, 'CREATE_NO_WINDOW').
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
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "No se especificó la aplicación a cerrar"
                    }
                try:
                    if _IS_WINDOWS:
                        exec_name = app_name if app_name.lower().endswith(".exe") else f"{app_name}.exe"
                        if "explorador" in app_name.lower():
                            exec_name = "explorer.exe"
                        subprocess.run(["taskkill", "/F", "/IM", exec_name], check=True, capture_output=True)
                    else:
                        subprocess.run(["pkill", "-f", app_name], check=True, capture_output=True)
                    result = f"Aplicación '{app_name}' cerrada correctamente."
                except Exception as e:
                    logger.error(f"Error cerrando {app_name}: {e}")
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": f"No se pudo cerrar '{app_name}'"
                    }

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
            elif action in ("type_text", "keyboard_type"):
                text = params.get("text", "")
                interval = params.get("interval", 0.03)
                pyautogui.write(text, interval=interval)
                result = {"chars_typed": len(text)}

            elif action == "press_key":
                key = params.get("key")
                pyautogui.press(key)
                result = f"Tecla presionada: {key}"

            elif action == "keyboard_hotkey":
                keys = params.get("keys", [])
                if isinstance(keys, str):
                    keys = [k.strip() for k in keys.replace("+", " ").split()]
                pyautogui.hotkey(*keys)
                result = {"keys": keys}

            elif action in ("move_mouse", "mouse_move"):
                x, y = params.get("x", 0), params.get("y", 0)
                duration = params.get("duration", 0.25)
                pyautogui.moveTo(x, y, duration)
                result = f"Ratón movido a ({x}, {y})"

            elif action in ("click", "mouse_click"):
                x, y = params.get("x"), params.get("y")
                button = params.get("button", "left")
                clicks = params.get("clicks", 1)
                interval = params.get("interval", 0.1)
                if x is not None and y is not None:
                    pyautogui.click(x, y, clicks=clicks, button=button, interval=interval)
                else:
                    pyautogui.click(clicks=clicks, button=button, interval=interval)
                result = {"x": x, "y": y, "button": button, "clicks": clicks}

            elif action == "mouse_drag":
                x1, y1 = params.get("x1", 0), params.get("y1", 0)
                x2, y2 = params.get("x2", 0), params.get("y2", 0)
                duration = params.get("duration", 0.5)
                button = params.get("button", "left")
                pyautogui.moveTo(x1, y1, 0.1)
                pyautogui.dragTo(x2, y2, duration, button=button)
                result = {"from": [x1, y1], "to": [x2, y2]}

            elif action == "ocr_screenshot":
                pytesseract = self._require("pytesseract")
                region = params.get("region")
                lang = params.get("lang", "spa+eng")
                img = pyautogui.screenshot(region=tuple(region) if region else None)
                text = pytesseract.image_to_string(img, lang=lang)
                result = {"text": text.strip(), "lang": lang}

            elif action == "ocr_image":
                pytesseract = self._require("pytesseract")
                PIL_Image = self._require("PIL.Image")
                p = Path(params.get("path", ""))
                if not p.exists():
                    return {"id": command_id, "status": "error", "error": f"Imagen no encontrada: {p}"}
                img = PIL_Image.open(str(p))
                text = pytesseract.image_to_string(img, lang=params.get("lang", "spa+eng"))
                result = {"text": text.strip(), "path": str(p)}

            elif action == "find_on_screen":
                cv2 = self._require("cv2")
                numpy = self._require("numpy")
                template_path = params.get("template_path", "")
                threshold = params.get("threshold", 0.8)
                region = params.get("region")
                tmpl_path = Path(template_path)
                if not tmpl_path.exists():
                    return {"id": command_id, "status": "error", "error": f"Template no encontrado: {template_path}"}
                screen = pyautogui.screenshot(region=tuple(region) if region else None)
                screen_np = numpy.array(screen.convert("RGB"))
                screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
                tmpl = cv2.imread(str(tmpl_path), cv2.IMREAD_GRAYSCALE)
                if tmpl is None:
                    return {"id": command_id, "status": "error", "error": f"No se pudo leer el template: {template_path}"}
                h, w = tmpl.shape
                match = cv2.matchTemplate(screen_gray, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(match)
                if max_val >= threshold:
                    cx, cy = max_loc[0] + w // 2, max_loc[1] + h // 2
                    if region:
                        cx, cy = cx + region[0], cy + region[1]
                    result = {"found": True, "x": cx, "y": cy, "confidence": round(float(max_val), 4)}
                else:
                    result = {"found": False, "confidence": round(float(max_val), 4)}

            elif action == "window_list":
                result = {"windows": self._get_window_titles()}

            elif action == "window_focus":
                result = self._focus_window(params.get("title", ""))

            elif action == "window_close":
                result = self._close_window(params.get("title", ""))
            
            elif action == "open_url":
                url = params.get("url", "").strip()
                if not url:
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": "No se especificó URL"
                    }
                try:
                    import webbrowser
                    webbrowser.open(url)
                    result = f"URL abierta en el navegador predeterminado: {url}"
                except Exception as e:
                    logger.error(f"Error abriendo URL {url}: {e}")
                    return {
                        "id": command_id,
                        "status": "error",
                        "error": f"No se pudo abrir la URL: {url}"
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
        
        # Al iniciar, actualizar el registro de aplicaciones.
        # FIX: update_app_registry() es síncrona y puede tardar varios
        # segundos en Windows (recorre Program Files + registro). Ejecutarla
        # directamente en el coroutine bloquea el event loop entero,
        # impidiendo que el agente procese mensajes WebSocket entrantes
        # mientras escanea. Se delega a un executor con run_in_executor.
        logger.info("Actualizando registro de aplicaciones instaladas...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, update_app_registry, self.registry_file)
            self.app_registry = load_app_registry(self.registry_file)
            logger.info(f"✓ Registro cargado: {len(self.app_registry)} aplicaciones disponibles")
        except Exception as e:
            logger.warning(f"No se pudo actualizar registro de apps: {e}")
            self.app_registry = {}
        
        while True:
            try:
                # Configuración de seguridad para WebSockets
                ssl_context = None
                if self.server_url.startswith("wss"):
                    ssl_context = ssl.create_default_context()

                async with websockets.connect(
                    self.server_url, 
                    ping_interval=20, 
                    ping_timeout=20,
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