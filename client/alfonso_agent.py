import asyncio
import json
import websockets
import subprocess
import pyautogui
import platform
import shutil
import webbrowser
import logging
import os

# Configuración de logs con escritura a archivo ui/logs/agent.log para visibilidad en GUI
ui_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(ui_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
log_file = os.path.join(logs_dir, "agent.log")

logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)

# Formateador de logs
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')

# Handler para consola
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Handler para archivo (agent.log)
try:
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"No se pudo crear el archivo de logs del agente: {e}")

pyautogui.FAILSAFE = True
IS_WINDOWS = platform.system() == "Windows"

try:
    from core.alfonso_agent_logic import AlfonsoAgentLogic
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from core.alfonso_agent_logic import AlfonsoAgentLogic

def _find_in_home(target_name: str) -> str | None:
    """Busca un archivo o carpeta en el perfil del usuario de forma rápida."""
    home = os.path.expanduser("~")
    # Ignorar carpetas ocultas o de sistema pesadas para que sea 100% rápido
    exclude_dirs = {
        "appdata", "program files", "program files (x86)", "windows", 
        ".git", ".vscode", "node_modules", "venv", ".venv", "__pycache__",
        "searches", "links", "contacts", "saved games", "desktop.ini"
    }
    
    # Primero buscamos en carpetas del primer nivel directo (Desktop, Documents, Downloads, etc.)
    priority_dirs = ["Desktop", "Escritorio", "Documents", "Documentos", "Downloads", "Descargas", "Pictures", "Imágenes"]
    for p_dir in priority_dirs:
        full_p_dir = os.path.join(home, p_dir)
        if os.path.exists(full_p_dir):
            for root, dirs, files in os.walk(full_p_dir):
                # Filtrar carpetas excluidas
                dirs[:] = [d for d in dirs if d.lower() not in exclude_dirs and not d.startswith(".")]
                
                # Buscar en carpetas
                for d in dirs:
                    if d.lower() == target_name.lower():
                        return os.path.join(root, d)
                # Buscar en archivos
                for f in files:
                    if f.lower() == target_name.lower():
                        return os.path.join(root, f)
                        
    # Búsqueda en la raíz del HOME
    for root, dirs, files in os.walk(home):
        depth = root[len(home):].count(os.sep)
        if depth > 2:
            dirs[:] = [] # No ir más profundo
            continue
            
        dirs[:] = [d for d in dirs if d.lower() not in exclude_dirs and not d.startswith(".")]
        
        for d in dirs:
            if d.lower() == target_name.lower():
                return os.path.join(root, d)
        for f in files:
            if f.lower() == target_name.lower():
                return os.path.join(root, f)
                
    return None


class AlfonsoAgent:

    def __init__(self, server_url="ws://localhost:8765"):
        self.server_url = server_url
        self.queue = asyncio.Queue()
        self.agent_logic = AlfonsoAgentLogic()
        self.gesture_controller = None

        self.handlers = {
            "system.open_app": self.open_app,
            "system.close_app": self.close_app,
            "system.open_url": self.open_url,
            "open_url": self.open_url,
            "system.browser_close": self.browser_close,
            "browser_close": self.browser_close,
            "keyboard.type": self.type_text,
            "keyboard.press": self.press_key,
            "keyboard.hotkey": self.press_hotkey,
            "mouse.move": self.move_mouse,
            "mouse.click": self.click_mouse,
            "mouse.drag": self.drag_mouse,
            "screen.screenshot": self.screenshot,
            "screen.ocr_screenshot": self.ocr_screenshot,
            "screen.ocr_image": self.ocr_image,
            "screen.find_on_screen": self.find_on_screen,
            "window.list": self.window_list,
            "window.focus": self.window_focus,
            "window.close": self.window_close,
            
            # Calendar
            "calendar.open": self.calendar_open,
            "calendar.close": self.calendar_close,
            "calendar.sync": self.calendar_sync,
            
            # Mail
            "mail.open": self.mail_open,
            "mail.close": self.mail_close,
            "mail.sync": self.mail_sync,
            
            # Dev Studio
            "dev_studio.open": self.dev_studio_open,
            "dev_studio.close": self.dev_studio_close,
            
            # Gestures
            "gestures.start": self.start_gestures,
            "gestures.stop": self.stop_gestures,
            
            # Filesystem
            "create_file": self.create_file,
            "read_file": self.read_file,
            "list_directory": self.list_directory,
            "create_directory": self.create_directory,
            "append_file": self.append_to_file,
            "delete_file": self.delete_file,
            "delete_directory": self.delete_directory,
            "move_file": self.move_file,
            "rename_file": self.rename_file,
        }

        self.mapping = {
            "open_app": "system.open_app",
            "close_app": "system.close_app",
            "open_url": "system.open_url",
            "browser_close": "system.browser_close",
            "type_text": "keyboard.type",
            "press_key": "keyboard.press",
            "move_mouse": "mouse.move",
            "click": "mouse.click",
            "append_file": "append_file",
            "rename_file": "rename_file",
            "start_gestures": "gestures.start",
            "stop_gestures": "gestures.stop",
        }

    # ---------------- NORMALIZACIÓN ----------------

    def normalize_action(self, action: str) -> str:
        """
        Traduce nombres de acción 'planos' (open_app, close_app, open_url...)
        al nombre con namespace que usan los handlers (system.open_app, etc.).
        Si la acción ya viene con namespace, se devuelve tal cual.
        """
        if action in self.handlers:
            return action
        return self.mapping.get(action, action)

    def _resolve_local_path(self, raw_path: str) -> str:
        if not raw_path:
            return raw_path
        # 1. Limpiar/corregir barras
        path = raw_path.replace("\\", "/")

        # Eliminar prefijos comunes como "mi ", "el ", "la "
        import re
        path = re.sub(r"\b(mi|el|la|los|las)\s+(escritorio|desktop|documentos|documents|descargas|downloads|imagenes|imágenes|pictures|musica|música|music|videos|perfil|usuario|home|inicio)\b", r"\2", path, flags=re.IGNORECASE)
        
        # 2. Corregir alucinación /usr/share/applications/
        if "/usr/share/applications/" in path and not path.endswith(".desktop"):
            filename = path.split("/")[-1]
            path = f"~/Desktop/{filename}"
            logger.info(f"Corrigiendo ruta de /usr/share/applications/ a Escritorio: {path}")

        # 3. Mapear rutas absolutas de otros sistemas (WSL/macOS) al home del usuario local
        match = re.match(r"^(?:/home/[^/]+|/Users/[^/]+|/mnt/[a-z]/Users/[^/]+)(/.*)$", path, re.IGNORECASE)
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

        # 5. Manejar variables de entorno
        if "%" in path:
            path = re.sub(r'%([^%]+)%', lambda m: os.environ.get(m.group(1), m.group(0)), path)

        # 6. Redireccionar carpetas comunes (Escritorio, Documentos, Descargas, etc.) al HOME del usuario
        parts = path.split("/")
        if len(parts) >= 1:
            for idx, part in enumerate(parts):
                part_lower = part.lower()
                target_folder = None
                
                if part_lower in ["desktop", "escritorio"]:
                    target_folder = "Desktop"
                elif part_lower in ["documents", "documentos"]:
                    target_folder = "Documents"
                elif part_lower in ["downloads", "descargas"]:
                    target_folder = "Downloads"
                elif part_lower in ["pictures", "imagenes", "imágenes"]:
                    target_folder = "Pictures"
                elif part_lower in ["music", "musica", "música"]:
                    target_folder = "Music"
                elif part_lower in ["videos"]:
                    target_folder = "Videos"
                elif part_lower in ["perfil", "usuario", "home", "inicio"]:
                    remainder = "/".join(parts[idx+1:])
                    path = os.path.join(os.path.expanduser("~"), remainder)
                    break
                
                if target_folder:
                    home = os.path.expanduser("~")
                    resolved_dir = os.path.join(home, target_folder)
                    # Si no existe en inglés, buscar en español
                    if not os.path.exists(resolved_dir):
                        spanish_mappings = {
                            "Desktop": "Escritorio",
                            "Documents": "Documentos",
                            "Downloads": "Descargas",
                            "Pictures": "Imágenes",
                            "Music": "Música",
                        }
                        if target_folder in spanish_mappings:
                            alt_dir = os.path.join(home, spanish_mappings[target_folder])
                            if os.path.exists(alt_dir):
                                resolved_dir = alt_dir
                                
                    remainder = "/".join(parts[idx+1:])
                    path = os.path.join(resolved_dir, remainder)
                    break

        resolved_path = os.path.normpath(path)
        
        # 7. Si la ruta final resuelta no existe, buscar el nombre del archivo/carpeta en el perfil
        if not os.path.exists(resolved_path):
            basename = os.path.basename(resolved_path)
            # Solo buscar si es un nombre simple o relativo corto
            if basename and (basename == path or "/" not in path):
                found_path = _find_in_home(basename)
                if found_path:
                    logger.info(f"Ruta no encontrada originalmente, resuelta mediante búsqueda en el Home: {found_path}")
                    return found_path

        return resolved_path

    # ---------------- SYSTEM ----------------

    def open_app(self, params):
        # El servidor (system_tools.py) manda la clave "command";
        # aceptamos también "app" por compatibilidad con otros llamantes.
        app = (params.get("command") or params.get("app") or "").strip()
        if not app:
            return {"error": "app vacío"}

        # Mapeo de comandos de Linux a Windows en el CLI
        if IS_WINDOWS:
            if "nautilus" in app.lower():
                app = "explorer.exe"
            elif app.lower().endswith("/code") or app.lower() == "code":
                app = "code"
            else:
                app = self.agent_logic._resolve_app_path(app)

        try:
            path = shutil.which(app) or app
            use_shell = IS_WINDOWS and (path.lower() in ["explorer.exe", "code"] or not path.endswith(".exe"))
            subprocess.Popen(path, shell=use_shell)
            return {"result": f"{app} abierto"}
        except Exception as e:
            try:
                if IS_WINDOWS:
                    subprocess.Popen(app, shell=True)
                    return {"result": f"{app} abierto (shell fallback)"}
                else:
                    raise
            except Exception as ex:
                return {"error": f"No se pudo abrir {app}: {ex}"}

    def close_app(self, params):
        app = (params.get("command") or params.get("app") or "").strip()
        if not app:
            return {"error": "app vacío"}

        try:
            if IS_WINDOWS:
                exec_name = app if app.lower().endswith(".exe") else f"{app}.exe"
                if exec_name.lower() == "explorer.exe" or "explorador" in app.lower():
                    logger.warning("Evitando taskkill en explorer.exe para no tumbar la shell de Windows. Usando Alt+F4.")
                    pyautogui.hotkey("alt", "f4")
                    return {"result": "Se envió Alt+F4 a la ventana activa"}
                subprocess.run(["taskkill", "/F", "/IM", exec_name], check=False)
            else:
                subprocess.run(["pkill", "-f", app], check=False)
            return {"result": f"{app} cerrado"}
        except Exception as e:
            return {"error": f"No se pudo cerrar {app}: {e}"}

    def open_url(self, params):
        url = params.get("url", "").strip()
        if not url:
            return {"error": "url vacía"}

        # Asegurar esquema para evitar que Windows explorer.exe abra "Documentos"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            if IS_WINDOWS:
                try:
                    subprocess.Popen(["explorer.exe", url], shell=False)
                except Exception:
                    os.startfile(url)
            else:
                import threading
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
            return {"result": url}
        except Exception as e:
            return {"error": f"No se pudo abrir la URL {url}: {e}"}

    def browser_close(self, params):
        results = []
        for browser_name in ["chrome", "firefox", "msedge"]:
            res = self.close_app({"command": browser_name})
            results.append(res)
        return {"result": "Navegadores cerrados", "details": results}

    # ---------------- INPUT ----------------

    def type_text(self, params):
        text = params.get("text", "")
        if not text:
            return {"error": "text vacío"}
        pyautogui.write(text)
        return {"result": "typed"}

    def press_key(self, params):
        key = params.get("key")
        if not key:
            return {"error": "key vacío"}
        pyautogui.press(key)
        return {"result": "pressed"}

    def move_mouse(self, params):
        pyautogui.moveTo(params.get("x", 0), params.get("y", 0))
        return {"result": "moved"}

    def click_mouse(self, params):
        pyautogui.click(button=params.get("button", "left"))
        return {"result": "clicked"}
    
    # ----------------FILES MANAGEMENT ----------------

    def create_file(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            # Asegurar que el directorio padre existe
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding="utf-8") as f:
                f.write(params.get("content", ""))
            return {"result": f"Archivo {path} creado"}
        except Exception as e:
            return {"error": f"No se pudo crear el archivo {path}: {e}"}
        
    def delete_file(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            if os.path.isdir(path):
                # Redirección automática si es un directorio
                shutil.rmtree(path)
                return {"result": f"Directorio {path} eliminado (redirección desde delete_file)"}
            os.remove(path)
            return {"result": f"Archivo {path} eliminado"}
        except Exception as e:
            return {"error": f"No se pudo eliminar el archivo {path}: {e}"}
        
    def create_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            os.makedirs(path, exist_ok=True)
            return {"result": f"Directorio {path} creado"}
        except Exception as e:
            return {"error": f"No se pudo crear el directorio {path}: {e}"}
    
    def delete_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            if os.path.isfile(path):
                # Redirección automática si es un archivo
                os.remove(path)
                return {"result": f"Archivo {path} eliminado (redirección desde delete_directory)"}
            shutil.rmtree(path)
            return {"result": f"Directorio {path} eliminado"}
        except Exception as e:
            return {"error": f"No se pudo eliminar el directorio {path}: {e}"}
    
    def list_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            if not os.path.exists(path):
                return {"error": f"La carpeta '{path}' no existe en el equipo."}
            if not os.path.isdir(path):
                return {"error": f"El objeto en '{path}' no es una carpeta."}
            files = os.listdir(path)
            return {"path": path, "result": files}
        except Exception as e:
            return {"error": f"No se pudo listar el directorio {path}: {e}"}
        
    def move_file(self, params):    
        src = params.get("src")
        dst = params.get("dst")
        if not src or not dst:
            return {"error": "src o dst vacío"}
        src = self._resolve_local_path(src)
        dst = self._resolve_local_path(dst)
        try:
            # Asegurar directorio de destino
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            return {"result": f"Archivo movido de {src} a {dst}"}
        except Exception as e:
            return {"error": f"No se pudo mover el archivo de {src} a {dst}: {e}"}
        
    def copy_file(self, params):
        src = params.get("src")
        dst = params.get("dst")
        if not src or not dst:
            return {"error": "src o dst vacío"}
        src = self._resolve_local_path(src)
        dst = self._resolve_local_path(dst)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)
            return {"result": f"Archivo copiado de {src} a {dst}"}
        except Exception as e:
            return {"error": f"No se pudo copiar el archivo de {src} a {dst}: {e}"}
    
    def read_file(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            with open(path, 'r', encoding="utf-8") as f:
                content = f.read()
            return {"result": content}
        except Exception as e:
            return {"error": f"No se pudo leer el archivo {path}: {e}"}
    
    def append_to_file(self, params):
        path = params.get("path")
        content = params.get("content", "")
        if not path:
            return {"error": "path vacío"}
        path = self._resolve_local_path(path)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a', encoding="utf-8") as f:
                f.write(content)
            return {"result": f"Contenido añadido al archivo {path}"}
        except Exception as e:
            return {"error": f"No se pudo añadir contenido al archivo {path}: {e}"}

    def rename_file(self, params):
        src = params.get("path") or params.get("src")
        dst = params.get("new_name") or params.get("dst")
        if not src or not dst:
            return {"error": "src o dst vacío"}
        src = self._resolve_local_path(src)
        # Si dst es solo un nombre de archivo, resolverlo en base al directorio de src resuelto
        if not os.path.isabs(dst) and not dst.startswith(".") and "/" not in dst and "\\" not in dst:
            dst = os.path.join(os.path.dirname(src), dst)
        else:
            dst = self._resolve_local_path(dst)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            return {"result": f"Archivo renombrado de {src} a {dst}"}
        except Exception as e:
            return {"error": f"No se pudo renombrar el archivo de {src} a {dst}: {e}"}

    def drag_mouse(self, params):
        try:
            pyautogui.dragTo(params.get("x2", 0), params.get("y2", 0), button=params.get("button", "left"), duration=params.get("duration", 0.5))
            return {"result": "dragged"}
        except Exception as e:
            return {"error": f"Error en drag_mouse: {e}"}

    def press_hotkey(self, params):
        keys = params.get("keys", [])
        if not keys:
            return {"error": "keys vacío"}
        try:
            pyautogui.hotkey(*keys)
            return {"result": "hotkey_pressed"}
        except Exception as e:
            return {"error": f"Error en press_hotkey: {e}"}

    def screenshot(self, params):
        try:
            from io import BytesIO
            import base64
            screenshot_img = pyautogui.screenshot()
            buffered = BytesIO()
            screenshot_img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            return {"message": "Captura de pantalla realizada.", "image_data": img_str}
        except Exception as e:
            return {"error": f"Error en screenshot: {e}"}

    def ocr_screenshot(self, params):
        return {"result": "Texto simulado OCR", "text": "Texto simulado OCR"}

    def ocr_image(self, params):
        return {"result": "Texto simulado OCR", "text": "Texto simulado OCR"}

    def find_on_screen(self, params):
        return {"x": 100, "y": 100}

    def window_list(self, params):
        return {"windows": [{"title": "Alfonso GUI", "id": 1}]}

    def window_focus(self, params):
        return {"result": "focused"}

    def window_close(self, params):
        return {"result": "closed"}

    def calendar_open(self, params):
        logger.info("calendar.open recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Calendario abierto."}

    def calendar_close(self, params):
        logger.info("calendar.close recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Calendario cerrado."}

    def calendar_sync(self, params):
        logger.info(f"calendar.sync recibido: {params}")
        return {"result": "ok", "message": "Sincronizado."}

    def mail_open(self, params):
        logger.info("mail.open recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Correo abierto."}

    def mail_close(self, params):
        logger.info("mail.close recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Correo cerrado."}

    def mail_sync(self, params):
        logger.info(f"mail.sync recibido: {params}")
        return {"result": "ok", "message": "Sincronizado."}

    def dev_studio_open(self, params):
        logger.info("dev_studio.open recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Dev Studio abierto."}

    def dev_studio_close(self, params):
        logger.info("dev_studio.close recibido del servidor. Informando al cliente GUI.")
        return {"result": "ok", "message": "Dev Studio cerrado."}

    # ---------------- GESTURES ----------------

    def start_gestures(self, params):
        logger.info(f"Iniciando control de gestos con params: {params}")
        try:
            if not self.gesture_controller:
                from services.gesture_controller import GestureController
                camera_index = params.get("camera_index", 0)
                self.gesture_controller = GestureController(camera_index=camera_index)
            self.gesture_controller.start()
            return {"result": "ok", "message": "Control de gestos iniciado correctamente."}
        except Exception as e:
            logger.exception("Error al iniciar el control de gestos")
            return {"error": f"Fallo al iniciar gestos: {e}"}

    def stop_gestures(self, params):
        logger.info("Deteniendo control de gestos...")
        try:
            if self.gesture_controller:
                self.gesture_controller.stop()
                return {"result": "ok", "message": "Control de gestos detenido correctamente."}
            return {"result": "ok", "message": "El control de gestos no estaba activo."}
        except Exception as e:
            logger.exception("Error al detener el control de gestos")
            return {"error": f"Fallo al detener gestos: {e}"}
    
    # ---------------- EXECUTION ----------------

    async def execute_action(self, msg):
        action = self.normalize_action(msg.get("action"))
        params = msg.get("params", {})
        cmd_id = msg.get("id")

        logger.info(f"===> [RECIBIDO] Acción: '{action}' | ID: {cmd_id} | Parámetros: {params}")

        handler = self.handlers.get(action)

        if not handler:
            logger.error(f"<=== [ERROR] Acción no soportada: '{action}' | ID: {cmd_id}")
            return {
                "id": cmd_id,
                "status": "error",
                "error": f"Acción no soportada: {action}"
            }

        try:
            loop = asyncio.get_running_loop()

            # 🔥 CRÍTICO: todo en thread para evitar bloquear websocket
            logger.info(f"Ejecutando handler para '{action}' en hilo secundario...")
            result = await loop.run_in_executor(None, handler, params)

            # Si el handler devolvió un error lógico (p.ej. parámetro
            # vacío), no lo reportamos como éxito.
            if isinstance(result, dict) and "error" in result:
                logger.error(f"<=== [FALLO LOGICO] Error en '{action}': {result['error']} | ID: {cmd_id}")
                return {
                    "id": cmd_id,
                    "status": "error",
                    "error": result["error"]
                }

            logger.info(f"<=== [EXITO] Comando '{action}' completado con resultado: {result} | ID: {cmd_id}")
            return {
                "id": cmd_id,
                "status": "success",
                "result": result
            }

        except Exception as e:
            logger.exception(f"<=== [EXCEPCION] Fallo al ejecutar '{action}': {e} | ID: {cmd_id}")
            return {
                "id": cmd_id,
                "status": "error",
                "error": str(e)
            }

    # ---------------- WORKER ----------------

    async def worker(self, ws):
        while True:
            msg = await self.queue.get()

            response = await self.execute_action(msg)

            try:
                await ws.send(json.dumps(response))
            except Exception as e:
                logger.warning(f"Error enviando respuesta: {e}")
                break

    # ---------------- RECEIVER ----------------

    async def receiver(self, ws):
        async for message in ws:
            try:
                await self.queue.put(json.loads(message))
            except json.JSONDecodeError:
                logger.warning("Mensaje inválido recibido")

    # ---------------- MAIN LOOP ----------------

    async def start(self):
        while True:
            try:
                async with websockets.connect(
                    self.server_url,
                    ping_interval=None,
                    max_size=2**23
                ) as ws:

                    logger.info("Conectado al bridge")

                    # Enviar handshake con info del sistema local
                    import getpass
                    try:
                        uname_str = getpass.getuser()
                    except Exception:
                        uname_str = os.path.basename(os.path.expanduser("~"))
                    
                    # Recopilar información detallada del hardware del cliente (de forma resiliente)
                    ram_total_gb = None
                    try:
                        import psutil
                        ram_total_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
                    except Exception:
                        try:
                            if platform.system() == "Windows":
                                # Fallback nativo de Windows si no está psutil
                                out = subprocess.check_output("wmic ComputerSystem get TotalPhysicalMemory", shell=True)
                                bytes_str = out.decode().split("\n")[1].strip()
                                ram_total_gb = round(int(bytes_str) / (1024 ** 3), 2)
                        except Exception:
                            pass
                    
                    screen_res = "Desconocida"
                    try:
                        import pyautogui
                        width, height = pyautogui.size()
                        screen_res = f"{width}x{height}"
                    except Exception:
                        pass
                        
                    # Obtener estructura básica del escritorio del cliente (primer nivel)
                    desktop_structure = []
                    try:
                        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
                        if not os.path.exists(desktop_dir):
                            desktop_dir = os.path.join(os.path.expanduser("~"), "Escritorio")
                            
                        if os.path.exists(desktop_dir):
                            for entry in os.scandir(desktop_dir):
                                if not entry.name.startswith(".") and not entry.name.startswith("desktop.ini"):
                                    marker = " (Carpeta)" if entry.is_dir() else ""
                                    desktop_structure.append(f"{entry.name}{marker}")
                            desktop_structure = sorted(desktop_structure)[:30]
                    except Exception as e:
                        desktop_structure = [f"Error leyendo escritorio: {e}"]
                        
                    # Obtener dispositivos de audio
                    audio_in = []
                    audio_out = []
                    try:
                        import sounddevice as sd
                        devices = sd.query_devices()
                        for d in devices:
                            name = d.get("name", "Desconocido")
                            idx = d.get("index")
                            if d.get("max_input_channels", 0) > 0:
                                audio_in.append(f"[{idx}] {name}")
                            if d.get("max_output_channels", 0) > 0:
                                audio_out.append(f"[{idx}] {name}")
                    except Exception:
                        pass
                    
                    # Generar/cargar client_id persistente en logs/client_config.json
                    import socket
                    import uuid
                    client_config_path = os.path.join(logs_dir, "client_config.json")
                    client_id = None
                    if os.path.exists(client_config_path):
                        try:
                            with open(client_config_path, "r", encoding="utf-8") as f:
                                client_id = json.load(f).get("client_id")
                        except Exception:
                            pass
                    if not client_id:
                        client_id = str(uuid.uuid4())
                        try:
                            with open(client_config_path, "w", encoding="utf-8") as f:
                                json.dump({"client_id": client_id}, f, indent=4)
                        except Exception:
                            pass

                    # Obtener hostname e IP local de forma resiliente
                    hostname = socket.gethostname()
                    ip_local = "127.0.0.1"
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        ip_local = s.getsockname()[0]
                        s.close()
                    except Exception:
                        try:
                            ip_local = socket.gethostbyname(hostname)
                        except Exception:
                            pass

                    handshake = {
                        "type": "handshake",
                        "client_id": client_id,
                        "hostname": hostname,
                        "ip_local": ip_local,
                        "system": platform.system(),
                        "release": platform.release(),
                        "username": uname_str,
                        "home": os.path.expanduser("~"),
                        "cwd": os.getcwd(),
                        "ram_total_gb": ram_total_gb,
                        "screen_resolution": screen_res,
                        "desktop_structure": desktop_structure,
                        "audio_devices": {
                            "input": audio_in[:6],
                            "output": audio_out[:6]
                        }
                    }
                    await ws.send(json.dumps(handshake))

                    worker_task = asyncio.create_task(self.worker(ws))
                    receiver_task = asyncio.create_task(self.receiver(ws))

                    done, pending = await asyncio.wait(
                        [worker_task, receiver_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )

                    for task in pending:
                        task.cancel()

            except Exception as e:
                logger.warning(f"Reconectando... {e}")
                await asyncio.sleep(3)


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8765"
    asyncio.run(AlfonsoAgent(url).start())