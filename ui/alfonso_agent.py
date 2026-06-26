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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")

pyautogui.FAILSAFE = True

IS_WINDOWS = platform.system() == "Windows"


class AlfonsoAgent:

    def __init__(self, server_url="ws://localhost:8765"):
        self.server_url = server_url
        self.queue = asyncio.Queue()

        self.handlers = {
            "system.open_app": self.open_app,
            "system.close_app": self.close_app,
            "system.open_url": self.open_url,
            "open_url": self.open_url,
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
            "type_text": "keyboard.type",
            "press_key": "keyboard.press",
            "move_mouse": "mouse.move",
            "click": "mouse.click",
            "append_file": "append_file",
            "rename_file": "rename_file",
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
        
        # 2. Corregir alucinación /usr/share/applications/
        if "/usr/share/applications/" in path and not path.endswith(".desktop"):
            filename = path.split("/")[-1]
            path = f"~/Desktop/{filename}"
            logger.info(f"Corrigiendo ruta de /usr/share/applications/ a Escritorio: {path}")

        # 3. Mapear rutas absolutas de otros sistemas (WSL/macOS) al home del usuario local
        import re
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

        # 6. Redireccionar Desktop/Escritorio al directorio real de Desktop
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

    # ---------------- SYSTEM ----------------

    def open_app(self, params):
        # El servidor (system_tools.py) manda la clave "command";
        # aceptamos también "app" por compatibilidad con otros llamantes.
        app = (params.get("command") or params.get("app") or "").strip()
        if not app:
            return {"error": "app vacío"}

        try:
            path = shutil.which(app) or app
            subprocess.Popen(path, shell=False)
            return {"result": f"{app} abierto"}
        except Exception as e:
            return {"error": f"No se pudo abrir {app}: {e}"}

    def close_app(self, params):
        app = (params.get("command") or params.get("app") or "").strip()
        if not app:
            return {"error": "app vacío"}

        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/IM", f"{app}.exe"], check=False)
            else:
                subprocess.run(["pkill", "-f", app], check=False)
            return {"result": f"{app} cerrado"}
        except Exception as e:
            return {"error": f"No se pudo cerrar {app}: {e}"}

    def open_url(self, params):
        url = params.get("url", "").strip()
        if not url:
            return {"error": "url vacía"}

        try:
            webbrowser.open(url)
            return {"result": url}
        except Exception as e:
            return {"error": f"No se pudo abrir la URL {url}: {e}"}

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
            files = os.listdir(path)
            return {"result": files}
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
                    ping_interval=60,
                    ping_timeout=300,
                    max_size=2**23
                ) as ws:

                    logger.info("Conectado al bridge")

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
    asyncio.run(AlfonsoAgent().start())