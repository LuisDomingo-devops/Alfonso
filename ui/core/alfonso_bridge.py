import asyncio
import json
import websockets
import uuid
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AlfonsoBridge:
    def __init__(self, host='0.0.0.0', port=8765):
        self.host = host
        self.port = port
        self.connected_clients = set()
        self.pending_commands = {}

    async def register(self, websocket):
        self.connected_clients.add(websocket)
        logger.info(f"Nuevo agente local conectado: {websocket.remote_address}")

    async def unregister(self, websocket):
        self.connected_clients.remove(websocket)
        logger.info(f"Agente local desconectado: {websocket.remote_address}")

    async def handle_connection(self, websocket):
        await self.register(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                logger.info(f"Respuesta recibida del agente: {data}")
                
                # Manejar la respuesta del comando
                command_id = data.get("id")
                if command_id in self.pending_commands:
                    future = self.pending_commands.pop(command_id)
                    future.set_result(data)
                else:
                    logger.warning(f"Recibida respuesta para un comando desconocido: {command_id}")
        except websockets.exceptions.ConnectionClosedError:
            logger.info("Conexión cerrada inesperadamente por el cliente.")
        finally:
            await self.unregister(websocket)

    async def send_command(self, action, params=None):
        if not self.connected_clients:
            logger.error("No hay agentes locales conectados para ejecutar el comando.")
            return {"status": "error", "error": "No hay agentes locales conectados."}

        command_id = str(uuid.uuid4())
        command = {
            "id": command_id,
            "action": action,
            "params": params or {}
        }

        # Por simplicidad, enviamos a todos los clientes conectados (normalmente solo habrá uno)
        message = json.dumps(command)
        
        # Crear un Future para esperar la respuesta
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_commands[command_id] = future

        logger.info(f"Enviando comando '{action}' con ID {command_id}")
        
        # Enviar a todos los clientes (en un escenario real, se seleccionaría el correcto)
        if self.connected_clients:
            await asyncio.gather(*(client.send(message) for client in self.connected_clients))

        try:
            # Esperar la respuesta con un timeout
            response = await asyncio.wait_for(future, timeout=30.0)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout esperando respuesta para el comando {command_id}")
            self.pending_commands.pop(command_id, None)
            return {"status": "error", "error": "Timeout esperando respuesta del agente local."}

    async def start(self):
        logger.info(f"Iniciando servidor Alfonso Bridge en {self.host}:{self.port}")
        async with websockets.serve(self.handle_connection, self.host, self.port):
            await asyncio.Future()  # Mantener el servidor corriendo para siempre

if __name__ == "__main__":
    bridge = AlfonsoBridge()
    
    # Para pruebas: Un pequeño bucle que lee comandos de la consola y los envía
    async def cli_interface(bridge):
        while True:
            try:
                # Esto es solo para pruebas manuales si se ejecuta el script directamente
                line = await asyncio.get_event_loop().run_in_executor(None, input, "Comando (ej. open_app:gedit): ")
                if not line: continue
                
                if ":" in line:
                    action, param = line.split(":", 1)
                    if action == "open_app":
                        params = {"command": param}
                    elif action == "type_text":
                        params = {"text": param}
                    else:
                        params = {"value": param}
                else:
                    action = line
                    params = {}
                
                result = await bridge.send_command(action, params)
                print(f"Resultado: {json.dumps(result, indent=2)}")
            except Exception as e:
                print(f"Error: {e}")

    async def main():
        bridge = AlfonsoBridge()
        # Correr el servidor y la interfaz CLI opcional en paralelo
        await asyncio.gather(
            bridge.start(),
            cli_interface(bridge)
        )

    asyncio.run(main())
