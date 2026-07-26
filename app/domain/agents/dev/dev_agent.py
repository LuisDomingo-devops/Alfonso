"""
DEV AGENT — Ingeniero de software experto.

¿QUÉ HACE?
Encapsula conocimientos en Python, C, C++, C# y realiza operaciones de escritura y prueba de código dentro de un sandbox aislado (data/dev_sandbox).

¿CUÁNDO LO HACE?
Cuando el PlannerOrchestrator identifica una consulta de desarrollo de software o cuando se solicita interacción directa a través de endpoints de /dev.

¿CÓMO LO HACE?
Utiliza OllamaClient para generar las respuestas técnicas de código basándose en el prompt del sistema precargado, y escribe/ejecuta comandos en un sandbox aislado mediante subprocess.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/domain/planner_orchestrator.py: Delega consultas de desarrollo a este agente.
- app/api/routes.py (antes routes_dev.py): Ofrece endpoints REST para interactuar con el sandbox de este agente.
- app/adapters/memory/vector_memory.py: Recupera pautas de diseño y plantillas de dev_knowledge.
- app/adapters/llm_client.py: Invoca el cliente LLM para generar código y respuestas.
"""

import os
import re
import subprocess
from pathlib import Path
from app.adapters.memory import vector_memory
from app.adapters.llm_client import OllamaClient
from app.utils.logger import orchestrator_logger

class DevAgent:
    """
    DevAgent: Ingeniero de software experto que encapsula conocimientos
    en Python, C, C++, C# y realiza operaciones de escritura y prueba
    de código dentro de un sandbox aislado.
    """
    def __init__(self):
        self.llm = OllamaClient()
        self.prompt_path = Path("app/prompts/dev_system.txt")
        self.sandbox_path = Path("data/dev_sandbox")
        self.sandbox_path.mkdir(parents=True, exist_ok=True)
        self._load_prompt()

    def _load_prompt(self):
        try:
            self.system_prompt = self.prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            orchestrator_logger.warning("Prompt de DevAgent no encontrado, usando fallback.")
            self.system_prompt = (
                "Eres MarcosDev, el ingeniero de software experto de Alfonso. "
                "Responde con tono técnico, riguroso y genera código limpio en Python, C, C++, o C#."
            )

    def write_to_sandbox(self, filename: str, content: str) -> str:
        """Escribe un archivo dentro del sandbox aislado y retorna la ruta completa."""
        file_path = self.sandbox_path / filename
        file_path.write_text(content, encoding="utf-8")
        orchestrator_logger.info("DevAgent guardó archivo en sandbox: %s", file_path)
        return str(file_path)

    def execute_command_in_sandbox(self, cmd: str) -> dict:
        """Ejecuta un comando en el directorio del sandbox y retorna stdout, stderr y exit code."""
        try:
            import shlex
            args = shlex.split(cmd)
            res = subprocess.run(
                args,
                shell=False,
                cwd=str(self.sandbox_path),
                capture_output=True,
                text=True,
                timeout=15
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Execution timed out (15s limits)"
            }
        except Exception as e:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e)
            }

    def _save_files_from_response(self, response_text: str) -> list[str]:
        """Extrae y guarda los archivos detectados en la respuesta en el sandbox."""
        file_blocks = re.findall(r"\[FILE:([\w\-\.]+)\]\s*```\w*\n(.*?)\n```", response_text, re.DOTALL)
        markdown_blocks = re.findall(r"```(\w*)\n(.*?)\n```", response_text, re.DOTALL)
        
        saved_files = []
        saved_set = set()
        
        # 1. Procesar bloques explícitos [FILE:nombre]
        for filename, content in file_blocks:
            filename = filename.strip()
            self.write_to_sandbox(filename, content)
            saved_files.append(filename)
            saved_set.add(filename)
            
        # 2. Procesar bloques con comentario interno (ej. # FILE:say_hello.py)
        for lang, content in markdown_blocks:
            match = re.search(r"(?:#|//|/\*)\s*FILE:\s*([\w\-\.]+)(?:\s*\*/)?", content, re.IGNORECASE)
            if match:
                filename = match.group(1).strip()
                if filename not in saved_set:
                    self.write_to_sandbox(filename, content)
                    saved_files.append(filename)
                    saved_set.add(filename)
        return saved_files

    def _determine_test_command(self, query: str, saved_files: list[str]) -> str | None:
        """Determina de forma heurística el comando de prueba a ejecutar."""
        # Buscar comandos explícitos pedidos por el usuario en la query
        m = re.search(r"\b(?:ejecuta|corre|prueba\s+con|comando)\s+[\"']?([^\"'\n]+)[\"']?", query, re.IGNORECASE)
        if m:
            return m.group(1).strip()
            
        # Archivos de pruebas explícitos
        test_files = [f for f in saved_files if f.startswith("test_") or f.endswith("_test.py") or f == "test.py"]
        if test_files:
            return f"pytest {test_files[0]}"
            
        # Archivo principal
        main_files = [f for f in saved_files if f in ("main.py", "app.py", "run.py")]
        if main_files:
            return f"python {main_files[0]}"
            
        # Primer archivo de python como fallback si no hay main
        py_files = [f for f in saved_files if f.endswith(".py")]
        if py_files:
            return f"python {py_files[0]}"
            
        return None

    async def generate_response(self, query: str) -> str:
        """
        Genera la respuesta técnica, escribe los archivos y prueba el código en un bucle
        de auto-corrección (debugging loop) de hasta 3 intentos.
        """
        # 1. Consultar base de conocimiento dev
        guidelines = vector_memory.query_dev(query, limit=3)
        dev_context = ""
        if guidelines:
            dev_context = "[Pautas de diseño y plantillas relevantes de dev_knowledge:]\n" + "\n".join(guidelines)
        else:
            dev_context = "No se encontraron pautas específicas en la base de conocimientos dev."

        # 2. Construir prompt para el LLM
        prompt = f"""{dev_context}

[REQUERIMIENTO DE DESARROLLO DE ALFONSO]
{query}

Por favor, diseña el código solicitado. Debes retornar el código completo en bloques markdown estándar con ```lenguaje.
Si es necesario guardar múltiples archivos, indícalo claramente con etiquetas [FILE:nombre_archivo] justo antes del bloque de código.
Ejemplo:
[FILE:main.py]
```python
print("Hello")
```
"""

        # Iniciar bucle de auto-corrección (Debugging Loop)
        max_attempts = 3
        current_attempt = 1
        current_prompt = prompt
        response_text = ""
        saved_files = []

        while current_attempt <= max_attempts:
            orchestrator_logger.info("DevAgent: Intento de generación y test %d/%d", current_attempt, max_attempts)
            try:
                response_text = await self.llm.generate(
                    current_prompt,
                    mode="chat",
                    memory=self.system_prompt,
                    options={
                        "num_ctx": 8192,
                        "temperature": 0.1 if current_attempt == 1 else 0.3,
                    }
                )
            except Exception as e:
                orchestrator_logger.exception("Error en la generación del LLM en DevAgent: %s", e)
                if current_attempt == 1:
                    return "Error llamando al modelo de lenguaje."
                break

            # Guardar archivos
            saved_files = self._save_files_from_response(response_text)
            
            # Determinar si hay un comando de pruebas que correr
            test_cmd = self._determine_test_command(query, saved_files)
            if not test_cmd:
                orchestrator_logger.info("DevAgent: No se determinó comando de prueba. Finalizando.")
                break

            # Ejecutar comando en el sandbox
            orchestrator_logger.info("DevAgent: Ejecutando comando de prueba en el sandbox: %s", test_cmd)
            run_result = self.execute_command_in_sandbox(test_cmd)

            if run_result["exit_code"] == 0:
                orchestrator_logger.info("DevAgent: ¡El comando se ejecutó con éxito! (exit_code 0)")
                response_text += f"\n\n[SISTEMA: Pruebas exitosas con comando: '{test_cmd}']"
                break
            else:
                orchestrator_logger.warning(
                    "DevAgent: El comando falló (exit_code %d). Iniciando auto-corrección.",
                    run_result["exit_code"]
                )
                
                # Construir el nuevo prompt acumulando la historia en formato de texto
                current_prompt = f"""{prompt}

---
Intento previo {current_attempt} fallido.
Respuesta del asistente anterior:
{response_text}

Resultado del comando de pruebas '{test_cmd}' ejecutado en el sandbox:
CÓDIGO DE SALIDA: {run_result['exit_code']}
STDOUT:
{run_result['stdout']}
STDERR:
{run_result['stderr']}

Por favor, analiza el error, corrige el código y genera la respuesta completa de nuevo incluyendo los bloques de código corregidos y las etiquetas [FILE:nombre] correspondientes.
"""
                current_attempt += 1

        if saved_files and "[SISTEMA: Archivos guardados" not in response_text:
            response_text += f"\n\n[SISTEMA: Archivos guardados con éxito en el Sandbox: {', '.join(saved_files)}]"

        return response_text

# Instancia global única
dev_agent = DevAgent()
