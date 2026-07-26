"""
ALFONSO BRIDGE — Puente de comunicación en tiempo real con el cliente.

¿QUÉ HACE?
Administra las conexiones de sockets en segundo plano y canaliza mensajes y comandos estructurados entre el servidor y la interfaz de usuario local.

¿CUÁNDO LO HACE?
Durante todo el ciclo de vida del servidor web (lifespan) y al procesar eventos interactivos.

¿CÓMO LO HACE?
Implementando un servidor WebSocket asíncrono y colas de control para emitir peticiones y sincronizaciones en formato JSON.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/main.py (inicia y detiene el bridge en los eventos de lifespan)
- app/api/routes.py (actualiza la información del cliente conectado y sincroniza el calendario)
"""

import asyncio
import json
import websockets
import uuid
import logging
import secrets

from app.domain.actions import ALLOWED_ACTIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bridge")


from app.domain.ports.bridge_port import BridgePort

class AlfonsoBridge(BridgePort):
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients = {}  # client_id -> WebSocket
        self.pending = {}  # cmd_id -> Future
        self.server = None
        self._client_info_dict = {}  # client_id -> info dict

    @property
    def client_info(self):
        # Devuelve la información del primer cliente conectado (por compatibilidad)
        if self.clients:
            first_id = list(self.clients.keys())[0]
            return self._client_info_dict.get(first_id)
        return None

    @client_info.setter
    def client_info(self, val):
        # Por compatibilidad (ej: rutas API que actualizan la info)
        if val and isinstance(val, dict):
            client_id = val.get("client_id")
            if client_id:
                if client_id in self._client_info_dict:
                    self._client_info_dict[client_id].update(val)
                else:
                    self._client_info_dict[client_id] = val

    async def start(self):
        logger.info(f"Bridge en {self.host}:{self.port}")
        self.server = await websockets.serve(
            self.handler,
            self.host,
            self.port,
            ping_interval=None,
        )

    async def stop(self):
        logger.info("Cerrando bridge...")

        for ws in list(self.clients.values()):
            try:
                await ws.close()
            except Exception as e:
                logger.warning(f"Error cerrando conexión en stop: {e}")

        self.clients.clear()
        self.pending.clear()
        self._client_info_dict.clear()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logger.info("Bridge cerrado correctamente")

    async def register(self, ws, client_id, metadata):
        # Cerrar cliente antiguo con el mismo ID para evitar fantasmas
        if client_id in self.clients:
            try:
                await self.clients[client_id].close()
            except Exception as e:
                logger.warning(f"Error cerrando cliente antiguo duplicado ({client_id}): {e}")
        self.clients[client_id] = ws
        self._client_info_dict[client_id] = metadata
        logger.info(f"Cliente conectado y registrado: {client_id} desde {ws.remote_address}")

    async def unregister(self, ws):
        client_id_to_remove = None
        for cid, conn in list(self.clients.items()):
            if conn == ws:
                client_id_to_remove = cid
                break
        if client_id_to_remove:
            self.clients.pop(client_id_to_remove, None)
            self._client_info_dict.pop(client_id_to_remove, None)
            logger.info(f"Cliente desconectado: {client_id_to_remove} ({ws.remote_address})")

    async def handler(self, ws):
        try:
            # Esperar el handshake como primer mensaje con un timeout de 5 segundos
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            if data.get("type") != "handshake":
                logger.warning("Conexión rechazada: el primer mensaje debe ser un handshake")
                await ws.close(code=4000, reason="Handshake required")
                return
            
            client_id = data.get("client_id")
            if not client_id:
                client_id = f"legacy-{ws.remote_address[0]}-{ws.remote_address[1]}"

            # Validar token si está configurado
            from app.config import settings
            token = data.get("token")
            expected_token = settings.get_client_token(client_id)
            if expected_token is not None:
                if not token or not secrets.compare_digest(token, expected_token):
                    logger.warning(f"Conexión rechazada: Token incorrecto o ausente para el cliente {client_id}")
                    await ws.close(code=4003, reason="Forbidden - Invalid Client Token")
                    return
            elif settings.ALFONSO_BRIDGE_TOKEN:
                if not token or not secrets.compare_digest(token, settings.ALFONSO_BRIDGE_TOKEN):
                    logger.warning("Conexión rechazada: Token incorrecto o ausente")
                    await ws.close(code=4003, reason="Forbidden - Invalid Token")
                    return

            # Asignar rol
            role = settings.get_client_role(client_id)
            data["role"] = role
            
            # Registrar cliente solo tras handshake exitoso
            await self.register(ws, client_id, data)
            logger.info("Handshake recibido y validado del cliente")
            try:
                import os
                os.makedirs("data", exist_ok=True)
                with open("data/last_client_info.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"No se pudo guardar last_client_info.json: {e}")

        except asyncio.TimeoutError:
            logger.warning("Conexión rechazada por timeout esperando handshake")
            await ws.close(code=4008, reason="Handshake timeout")
            return
        except Exception as e:
            logger.error(f"Error durante el handshake inicial: {e}")
            await ws.close(code=4000, reason="Invalid request")
            return

        try:
            async for msg in ws:
                data = json.loads(msg)

                # Si vuelven a mandar un handshake, simplemente lo actualizamos o ignoramos
                if data.get("type") == "handshake":
                    client_id = data.get("client_id")
                    if not client_id:
                        client_id = f"legacy-{ws.remote_address[0]}-{ws.remote_address[1]}"
                    token = data.get("token")
                    from app.config import settings
                    expected_token = settings.get_client_token(client_id)
                    if expected_token is not None:
                        if not secrets.compare_digest(token, expected_token):
                            logger.warning(f"Handshake subsiguiente rechazado: token inválido para el cliente {client_id}")
                            await ws.close(code=4003, reason="Forbidden - Invalid Client Token")
                            return
                    elif settings.ALFONSO_BRIDGE_TOKEN and not secrets.compare_digest(token, settings.ALFONSO_BRIDGE_TOKEN):
                        logger.warning("Handshake subsiguiente rechazado: token global inválido")
                        await ws.close(code=4003, reason="Forbidden - Invalid Token")
                        return
                    
                    role = settings.get_client_role(client_id)
                    data["role"] = role
                    if client_id:
                        self._client_info_dict[client_id] = data
                    continue

                cmd_id = data.get("id")
                fut = self.pending.pop(cmd_id, None)

                if fut is None:
                    logger.warning("Respuesta desconocida: %s", data)
                elif fut.done():
                    logger.warning("Respuesta tardía descartada (future ya cerrado): %s", cmd_id)
                else:
                    fut.set_result(data)

        except websockets.ConnectionClosed as e:
            logger.info("Conexión cerrada por el cliente (%s): %s", ws.remote_address, e)

        finally:
            await self.unregister(ws)

    def has_clients(self):
        return bool(self.clients)

    def has_client(self, client_id):
        return client_id in self.clients

    async def send_command(self, action, params=None, timeout=60, client_id=None):
        if action not in ALLOWED_ACTIONS:
            return {
                "status": "error",
                "error": f"Action no permitida: {action}"
            }

        if not self.clients:
            return {"status": "error", "error": "No hay clientes conectados"}

        # Si se especifica client_id, enviar solo a ese cliente. Si no, al primero.
        target_ws = None
        if client_id:
            target_ws = self.clients.get(client_id)
            if not target_ws:
                return {"status": "error", "error": f"El cliente '{client_id}' no está conectado"}
        else:
            # Fallback al primer cliente
            first_client_id = list(self.clients.keys())[0]
            target_ws = self.clients[first_client_id]

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
            await target_ws.send(msg)
            try:
                response = await asyncio.wait_for(fut, timeout=timeout)
                return response
            except asyncio.TimeoutError:
                return {"status": "error", "error": "Timeout"}
        except Exception as e:
            return {"status": "error", "error": f"Error de comunicación con el cliente: {e}"}

        finally:
            self.pending.pop(cmd_id, None)


bridge = AlfonsoBridge()

if __name__ == "__main__":
    asyncio.run(bridge.start())
    asyncio.get_event_loop().run_forever()