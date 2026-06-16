"""
alfonso_bridge.py — servidor WebSocket para el agente local de escritorio.

El bridge permite que `ui/alfonso_agent.py` en Windows se conecte y reciba
comandos como `open_app`, `type_text`, `press_key`, etc.

El servidor arranca junto con FastAPI y expone un endpoint WebSocket en el
puerto configurado. El tool `open_application` delega aquí si hay un agente
local conectado.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

import websockets
from websockets.legacy.server import WebSocketServerProtocol

from app.config import settings

logger = logging.getLogger("alfonso.bridge")


class AlfonsoBridge:
    def __init__(self, host: str = settings.BRIDGE_HOST, port: int = settings.BRIDGE_PORT, timeout: float = settings.BRIDGE_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connected_clients: set[WebSocketServerProtocol] = set()
        self.pending_commands: dict[str, asyncio.Future] = {}
        self._server: Any | None = None

    def has_clients(self) -> bool:
        return bool(self.connected_clients)

    async def register(self, websocket: WebSocketServerProtocol) -> None:
        self.connected_clients.add(websocket)
        logger.info("Nuevo agente local conectado: %s", websocket.remote_address)

    async def unregister(self, websocket: WebSocketServerProtocol) -> None:
        self.connected_clients.discard(websocket)
        logger.info("Agente local desconectado: %s", websocket.remote_address)

    async def handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        await self.register(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                logger.info("Respuesta recibida del agente local: %s", data)
                command_id = data.get("id")
                if command_id in self.pending_commands:
                    future = self.pending_commands.pop(command_id)
                    if not future.done():
                        future.set_result(data)
                else:
                    logger.warning("Recibida respuesta para un comando desconocido: %s", command_id)
        except websockets.exceptions.ConnectionClosedError:
            logger.info("Conexión cerrada inesperadamente por el agente local.")
        finally:
            await self.unregister(websocket)

    async def send_command(self, action: str, params: dict | None = None) -> dict:
        if not self.has_clients():
            logger.error("No hay agentes locales conectados para ejecutar el comando '%s'.", action)
            return {"status": "error", "error": "No hay agentes locales conectados."}

        command_id = str(uuid.uuid4())
        payload = {
            "id": command_id,
            "action": action,
            "params": params or {},
        }
        message = json.dumps(payload)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_commands[command_id] = future

        send_tasks = [client.send(message) for client in self.connected_clients]
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "Error enviando comando al agente local (%s): %s",
                    list(self.connected_clients)[idx].remote_address,
                    result,
                )

        try:
            response = await asyncio.wait_for(future, timeout=self.timeout)
            return response
        except asyncio.TimeoutError:
            logger.error("Timeout esperando respuesta del agente local para el comando %s", command_id)
            self.pending_commands.pop(command_id, None)
            return {"status": "error", "error": "Timeout esperando respuesta del agente local."}

    async def start(self) -> None:
        self._server = await websockets.serve(self.handle_connection, self.host, self.port)
        logger.info("Alfonso Bridge WebSocket iniciado en %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Alfonso Bridge WebSocket detenido")


bridge = AlfonsoBridge()
