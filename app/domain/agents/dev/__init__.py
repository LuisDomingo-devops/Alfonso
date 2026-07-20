"""
AGENTE DEV — Inicialización del subpaquete dev.

¿QUÉ HACE?
Expone e inicializa el agente de desarrollo (DevAgent).

¿CUÁNDO LO HACE?
Al importar dev_agent desde app.domain.agents.dev.

¿CÓMO LO HACE?
Sirve como marcador de paquete e importa el agente.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/domain/agents/dev/dev_agent.py: Archivo que contiene la lógica principal del agente.
"""
from app.domain.agents.dev.dev_agent import dev_agent
