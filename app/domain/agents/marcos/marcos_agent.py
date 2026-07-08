"""
MARCOS AGENT — Abogado experto en legislación española.

¿QUÉ HACE?
Encapsula el conocimiento jurídico (Constitución Española, Código Civil, Código Penal) para responder consultas legales o redactar borradores de correo electrónico formales basándose en búsquedas semánticas.

¿CUÁNDO LO HACE?
Cuando el PlannerOrchestrator identifica una consulta de carácter legal o cuando se solicita un borrador inteligente para responder a un correo electrónico.

¿CÓMO LO HACE?
Realiza búsquedas semánticas en la base de datos ChromaDB mediante vector_memory.query_legal para recuperar artículos relevantes, inyecta este contexto legislativo en OllamaClient y genera la respuesta formal y precisa.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/planner_orchestrator.py: Delega consultas legales a este agente.
- app/tools/mail_tools.py: Llama a este agente para generar borradores de correo inteligente si se detecta carácter legal.
- app/core/vector_memory.py: Proporciona la funcionalidad de búsqueda semántica en la legislación.
- app/core/llm_client.py: Invoca el cliente LLM para generar el dictamen o borrador legal.
"""

import os
from pathlib import Path
from app.adapters.memory import vector_memory
from app.adapters.llm_client import OllamaClient
from app.utils.logger import orchestrator_logger

class MarcosAgent:
    """
    Marcos Agent: Abogado experto que encapsula el conocimiento jurídico
    (Constitución Española, Código Civil, Código Penal) y genera respuestas
    legales utilizando ChromaDB y LLM.
    """
    def __init__(self):
        self.llm = OllamaClient()
        self.prompt_path = Path("app/prompts/marcos_system.txt")
        self._load_prompt()

    def _load_prompt(self):
        try:
            self.system_prompt = self.prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            orchestrator_logger.warning("Prompt de Marcos no encontrado, usando fallback.")
            self.system_prompt = (
                "Eres Marcos, el abogado experto del family office de Luis Domingo. "
                "Responde con tono formal, riguroso y basándote en el derecho civil, penal y constitucional de España."
            )

    async def generate_response(self, query: str, context_email: dict = None) -> str:
        """
        Genera una respuesta legal a una consulta o redacta un borrador de correo.
        """
        # 1. Recuperar artículos de ley relevantes usando la búsqueda semántica
        # Si hay un correo de contexto, combinamos la consulta con el correo para una mejor búsqueda
        search_query = query
        if context_email:
            search_query = f"{context_email.get('subject', '')} {context_email.get('body', '')} {query}"
            
        legal_articles = vector_memory.query_legal(search_query, limit=5)
        
        if legal_articles:
            legal_context = "Artículos y legislación española relevante encontrada:\n" + "\n\n".join(legal_articles)
        else:
            legal_context = "No se encontraron artículos específicos en la base de datos de legislación."

        # 2. Construir el prompt para el LLM
        prompt = f"""[CONTEXTO LEGAL Y HECHOS]
{legal_context}

"""
        if context_email:
            prompt += f"""[CORREO ELECTRÓNICO A RESPONDER]
Remitente: {context_email.get('sender')}
Asunto: {context_email.get('subject')}
Cuerpo: {context_email.get('body')}

Por favor, redacta un borrador de correo electrónico formal de respuesta basándote en la legislación anterior. Responde EXCLUSIVAMENTE con el cuerpo del correo propuesto, sin comentarios ni explicaciones adicionales, firmado como 'Luis Domingo' (o su representante).
"""
        else:
            prompt += f"""[CONSULTA LEGAL DEL USUARIO]
{query}

Por favor, asesora y responde a esta consulta de forma rigurosa basándote en los artículos de ley anteriores.
"""

        # 3. Invocar al LLM
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        try:
            payload = {
                "model": self.llm.llm_client.settings.MODEL_NAME if hasattr(self.llm, "llm_client") else "qwen2.5:1.5b",
                "messages": messages,
                "stream": False,
                "keep_alive": -1,
                "options": {
                    "num_ctx": 4096,  # Mayor contexto para leyes
                    "temperature": 0.2, # Respuestas más precisas y formales
                },
            }
            from app.adapters.http_client import client
            from app.config import settings
            
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )
            if response.status_code == 200:
                data = response.json()
                return data["message"]["content"].strip()
            else:
                orchestrator_logger.error("Error llamando a Ollama para Marcos: %s", response.text)
        except Exception as e:
            orchestrator_logger.exception("Error en la ejecución del agente Marcos: %s", e)
            
        # Fallback usando el método estándar si falla la llamada directa
        return await self.llm.generate(
            prompt,
            mode="chat",
            memory=self.system_prompt
        )

# Instancia global única
marcos_agent = MarcosAgent()
