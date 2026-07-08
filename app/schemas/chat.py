"""
CHAT SCHEMAS — Modelos de datos para chat de Alfonso.

¿QUÉ HACE?
Define las estructuras Pydantic utilizadas para el envío e intercambio de mensajes de chat.

¿CUÁNDO LO HACE?
Al serializar/deserializar información de entrada y salida del endpoint /chat.

¿CÓMO LO HACE?
Heredando de BaseModel de Pydantic para validar campos obligatorios y opcionales.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py (utiliza estos esquemas en los payloads de endpoints REST)
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str