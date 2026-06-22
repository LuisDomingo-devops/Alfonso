import asyncio
import json
import websockets
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bridge")


ALLOWED_ACTIONS = {
    "system.open_app",
    "system.close_app",
    "open_app",     # <- nombre real que usa system_tools.py (open_application)
    "close_app",    # <- nombre real que usa system_tools.py (close_application)
    "open_url",     # <- nombre real que usa system_tools.py (open_url)
    "create_file",
    "read_file",
    "list_directory",
    "create_directory",
    "append_file",
    "delete_file",
    "delete_directory",
    "move_file",
    "rename_file", # <- nombre real que usa system_tools.py (delete_folder)
    "keyboard.type",
    "keyboard.press",
    "mouse.move",
    "mouse.click",
    "mouse.drag",
    "window.focus",
    "window.close",
    "screen.screenshot",
}

class AlfonsoBridge:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.pending = {}
        self.server = None

    async def start(self):
        logger.info(f"Bridge en {self.host}:{self.port}")
        # ping_interval/ping_timeout más generosos: con el modelo actual
        # (qwen2.5:1.5b) una llamada /chat puede tardar 40-60s. Si el loop
        # de asyncio se queda ocupado durante ese tiempo, el servidor de
        # websockets puede no mandar el ping a tiempo con los valores por
        # defecto (20s/20s) y cerrar la conexión con "ping timeout" aunque
        # el agente local siga vivo (es justo lo que pasó en tu log).
        self.server = await websockets.serve(
            self.handler,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=90,
        )

    async def stop(self):
        logger.info("Cerrando bridge...")

        for ws in list(self.clients):
            await ws.close()

        self.clients.clear()
        self.pending.clear()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logger.info("Bridge cerrado correctamente")

    async def register(self, ws):
        self.clients.add(ws)
        logger.info(f"Cliente conectado: {ws.remote_address}")

    async def unregister(self, ws):
        self.clients.discard(ws)
        logger.info(f"Cliente desconectado: {ws.remote_address}")

    async def handler(self, ws):
        await self.register(ws)
        try:
            async for msg in ws:
                data = json.loads(msg)

                cmd_id = data.get("id")
                fut = self.pending.pop(cmd_id, None)

                if fut is None:
                    logger.warning("Respuesta desconocida: %s", data)
                elif fut.done():
                    logger.warning("Respuesta tardía descartada (future ya cerrado): %s", cmd_id)
                else:
                    fut.set_result(data)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info("Conexión cerrada por el cliente (%s): %s", ws.remote_address, e)

        finally:
            await self.unregister(ws)

    def has_clients(self):
        return bool(self.clients)

    async def send_command(self, action, params=None, timeout=20):
        if action not in ALLOWED_ACTIONS:
            return {
                "status": "error",
                "error": f"Action no permitida: {action}"
            }

        if not self.clients:
            return {"status": "error", "error": "No hay clientes conectados"}

        cmd_id = str(uuid.uuid4())

        payload = {
            "id": cmd_id,
            "action": action,
            "params": params or {}
        }

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending[cmd_id] = fut

        msg = json.dumps(payload)

        try:
            results = await asyncio.gather(
                *(c.send(msg) for c in self.clients),
                return_exceptions=True
            )

            if all(isinstance(r, Exception) for r in results):
                return {"status": "error", "error": "Cliente desconectado"}

            try:
                response = await asyncio.wait_for(fut, timeout=timeout)
                return response
            except asyncio.TimeoutError:
                return {"status": "error", "error": "Timeout"}

        finally:
            # Se ejecuta siempre: timeout, cancelación externa, error de envío...
            self.pending.pop(cmd_id, None)


bridge = AlfonsoBridge()

if __name__ == "__main__":
    asyncio.run(bridge.start())
    asyncio.get_event_loop().run_forever()