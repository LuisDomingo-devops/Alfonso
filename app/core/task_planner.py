import json
import httpx
from typing import List, Dict, Any
from pydantic import BaseModel
from app.core.tool_registry import get_tools_info
from app.utils.logger import tool_registry_logger

class TaskStep(BaseModel):
    step_number: int
    tool_name: str
    args: Dict[str, Any]
    thought: str

class TaskPlan(BaseModel):
    goal: str
    steps: List[TaskStep]
    estimated_complexity: str

class TaskPlanner:
    """
    Agente responsable de descomponer una petición del usuario en pasos ejecutables
    utilizando las herramientas registradas en el sistema.
    """
    
    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = f"{base_url}/api/generate"
        self.logger = tool_registry_logger

    def _build_system_prompt(self) -> str:
        tools = get_tools_info()
        tools_desc = "\n".join([f"- {t['name']}: {t['description']}" for t in tools])
        
        return f"""Eres el Task Planner de Alfonso. Tu objetivo es crear un plan de ejecución.
Herramientas disponibles:
{tools_desc}

Responde SIEMPRE en formato JSON siguiendo esta estructura:
{{
  "goal": "objetivo final",
  "steps": [
    {{ "step_number": 1, "tool_name": "nombre", "args": {{}}, "thought": "por qué usas esto" }}
  ],
  "estimated_complexity": "baja/media/alta"
}}"""

    async def create_plan(self, user_input: str) -> TaskPlan:
        system_prompt = self._build_system_prompt()
        full_prompt = f"{system_prompt}\n\nUsuario: {user_input}\n\nPlan en JSON:"
        
        self.logger.info("Solicitando plan a Ollama para: %s", user_input)
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.base_url,
                    json={
                        "model": self.model,
                        "prompt": full_prompt,
                        "stream": False,
                        "format": "json"
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                plan_data = json.loads(result["response"])
                
                return TaskPlan(**plan_data)
                
            except Exception as e:
                self.logger.error("Error generando plan con Ollama: %s", str(e))
                raise

    def execute_step(self, step: TaskStep):
        # Esta lógica se conectará con el Orquestador de la Fase 2
        pass
