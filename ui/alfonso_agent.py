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

    def normalize_action(self, action: str):
        return self.handlers.get(action) and action or self.mapping.get(action, action)

    # ---------------- SYSTEM ----------------

    def open_app(self, params):
        app = params.get("app", "").strip()
        if not app:
            return {"error": "app vacío"}

        path = shutil.which(app) or app

        subprocess.Popen(path, shell=False)
        return {"result": f"{app} abierto"}

    def close_app(self, params):
        app = params.get("app", "").strip()

        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/IM", f"{app}.exe"])
        else:
            subprocess.run(["pkill", "-f", app])

        return {"result": f"{app} cerrado"}

    def open_url(self, params):
        url = params.get("url", "").strip()
        if not url:
            return {"error": "url vacía"}

        webbrowser.open(url)
        return {"result": url}

    # ---------------- INPUT ----------------

    def type_text(self, params):
        pyautogui.write(params.get("text", ""))
        return {"result": "typed"}

    def press_key(self, params):
        pyautogui.press(params.get("key"))
        return {"result": "pressed"}

    def move_mouse(self, params):
        pyautogui.moveTo(params.get("x", 0), params.get("y", 0))
        return {"result": "moved"}

    def click_mouse(self, params):
        pyautogui.click(button=params.get("button", "left"))
        return {"result": "clicked"}

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