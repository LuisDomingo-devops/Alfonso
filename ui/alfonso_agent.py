import asyncio
import json
import websockets
import subprocess
import pyautogui
import platform
import shutil
import webbrowser
import logging

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
            "keyboard.type": self.type_text,
            "keyboard.press": self.press_key,
            "mouse.move": self.move_mouse,
            "mouse.click": self.click_mouse,
        }

        self.mapping = {
            "open_app": "system.open_app",
            "close_app": "system.close_app",
            "open_url": "system.open_url",
            "type_text": "keyboard.type",
            "press_key": "keyboard.press",
            "move_mouse": "mouse.move",
            "click": "mouse.click",
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
        try:
            with open(path, 'w') as f:
                f.write(params.get("content", ""))
            return {"result": f"Archivo {path} creado"}
        except Exception as e:
            return {"error": f"No se pudo crear el archivo {path}: {e}"}
        
    def delete_file(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        try:
            os.remove(path)
            return {"result": f"Archivo {path} eliminado"}
        except Exception as e:
            return {"error": f"No se pudo eliminar el archivo {path}: {e}"}
        
    def create_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        try:
            os.makedirs(path, exist_ok=True)
            return {"result": f"Directorio {path} creado"}
        except Exception as e:
            return {"error": f"No se pudo crear el directorio {path}: {e}"}
    
    def delete_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        try:
            shutil.rmtree(path)
            return {"result": f"Directorio {path} eliminado"}
        except Exception as e:
            return {"error": f"No se pudo eliminar el directorio {path}: {e}"}
    
    def list_directory(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
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
        try:
            shutil.move(src, dst)
            return {"result": f"Archivo movido de {src} a {dst}"}
        except Exception as e:
            return {"error": f"No se pudo mover el archivo de {src} a {dst}: {e}"}
        
    def copy_file(self, params):
        src = params.get("src")
        dst = params.get("dst")
        if not src or not dst:
            return {"error": "src o dst vacío"}
        try:
            shutil.copy(src, dst)
            return {"result": f"Archivo copiado de {src} a {dst}"}
        except Exception as e:
            return {"error": f"No se pudo copiar el archivo de {src} a {dst}: {e}"}
    
    def read_file(self, params):
        path = params.get("path")
        if not path:
            return {"error": "path vacío"}
        try:
            with open(path, 'r') as f:
                content = f.read()
            return {"result": content}
        except Exception as e:
            return {"error": f"No se pudo leer el archivo {path}: {e}"}
    
    def append_to_file(self, params):
        path = params.get("path")
        content = params.get("content", "")
        if not path:
            return {"error": "path vacío"}
        try:
            with open(path, 'a') as f:
                f.write(content)
            return {"result": f"Contenido añadido al archivo {path}"}
        except Exception as e:
            return {"error": f"No se pudo añadir contenido al archivo {path}: {e}"}
    
    
    # ---------------- EXECUTION ----------------

    async def execute_action(self, msg):
        action = self.normalize_action(msg.get("action"))
        params = msg.get("params", {})
        cmd_id = msg.get("id")

        handler = self.handlers.get(action)

        if not handler:
            return {
                "id": cmd_id,
                "status": "error",
                "error": f"Acción no soportada: {action}"
            }

        try:
            loop = asyncio.get_running_loop()

            # 🔥 CRÍTICO: todo en thread para evitar bloquear websocket
            result = await loop.run_in_executor(None, handler, params)

            # Si el handler devolvió un error lógico (p.ej. parámetro
            # vacío), no lo reportamos como éxito.
            if isinstance(result, dict) and "error" in result:
                return {
                    "id": cmd_id,
                    "status": "error",
                    "error": result["error"]
                }

            return {
                "id": cmd_id,
                "status": "success",
                "result": result
            }

        except Exception as e:
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
                    ping_interval=20,
                    ping_timeout=20,
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