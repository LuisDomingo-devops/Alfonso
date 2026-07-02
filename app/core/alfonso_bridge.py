import asyncio
import json
import websockets
import uuid
import logging

from app.core.actions import ALLOWED_ACTIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bridge")


class AlfonsoBridge:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.pending = {}
        self.server = None
        self.client_info = None

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
            ping_interval=None,
        )

    async def stop(self):
        logger.info("Cerrando bridge...")

        for ws in list(self.clients):
            await ws.close()

        self.clients.clear()
        self.pending.clear()
        self.client_info = None

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logger.info("Bridge cerrado correctamente")

    async def register(self, ws):
        # Cerrar clientes antiguos para evitar zombies/fantasmas (duplicación de comandos)
        for client in list(self.clients):
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Error cerrando cliente antiguo: {e}")
        self.clients.clear()
        self.clients.add(ws)
        logger.info(f"Cliente conectado: {ws.remote_address}")

    async def unregister(self, ws):
        self.clients.discard(ws)
        self.client_info = None
        logger.info(f"Cliente desconectado: {ws.remote_address}")

    async def handler(self, ws):
        await self.register(ws)
        try:
            async for msg in ws:
                data = json.loads(msg)

                # Interceptar handshake del cliente
                if data.get("type") == "handshake":
                    self.client_info = data
                    logger.info("Handshake recibido del cliente")
                    try:
                        import os
                        os.makedirs("data", exist_ok=True)
                        with open("data/last_client_info.json", "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=4)
                    except Exception as e:
                        logger.error(f"No se pudo guardar last_client_info.json: {e}")
                    continue

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

    async def send_command(self, action, params=None, timeout=60):
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