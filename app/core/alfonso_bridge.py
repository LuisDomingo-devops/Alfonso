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
    "system.open_url",
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
        self.server = await websockets.serve(self.handler, self.host, self.port)

    async def stop(self):
        logger.info("Cerrando bridge...")

        # cerrar clientes
        for ws in list(self.clients):
            await ws.close()

        self.clients.clear()
        self.pending.clear()

        # cerrar server websocket
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
                if cmd_id in self.pending:
                    fut = self.pending.pop(cmd_id)
                    fut.set_result(data)
                else:
                    logger.warning(f"Respuesta desconocida: {data}")

        finally:
            await self.unregister(ws)

    def has_clients(self):
        return bool(self.clients)

    async def send_command(self, action, params=None):
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

        results = await asyncio.gather(
            *(c.send(msg) for c in self.clients),
            return_exceptions=True
        )

        if all(isinstance(r, Exception) for r in results):
            self.pending.pop(cmd_id, None)
            return {"status": "error", "error": "Cliente desconectado"}

        try:
            response = await asyncio.wait_for(fut, timeout=30)
            return response
        except asyncio.TimeoutError:
            self.pending.pop(cmd_id, None)
            return {"status": "error", "error": "Timeout"}

    async def start(self):
        logger.info(f"Bridge en {self.host}:{self.port}")
        self.server = await websockets.serve(self.handler, self.host, self.port)


bridge = AlfonsoBridge()

if __name__ == "__main__":
    asyncio.run(bridge.start())
    asyncio.get_event_loop().run_forever()