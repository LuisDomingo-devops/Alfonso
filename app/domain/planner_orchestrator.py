"""
PLANNER ORCHESTRATOR — Planificador y orquestador central de Alfonso.

¿QUÉ HACE?
Orquesta y ejecuta el ciclo de vida del planificador (fase de intención, planificación y ejecución de herramientas). Es el pipeline principal por el que pasa cada petición de usuario.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py: Invoca este orquestador a través de /chat.
- app/domain/agents/dev/dev_agent.py: Delega consultas de desarrollo de software.
- app/domain/agents/marcos/marcos_agent.py: Delega consultas de legislación española.
- app/adapters/tool_registry.py: Busca y proporciona las herramientas a ejecutar.
"""

from __future__ import annotations

import asyncio
import inspect
import re

from app.domain.ports.llm_port import LLMPort
from app.domain.ports.memory_port import MemoryPort, VectorMemoryPort
from app.domain.ports.bridge_port import BridgePort
from app.domain.ports.calendar_port import CalendarPort
from app.adapters.tool_registry import (
    get_tool,
    is_client_tool,
    get_client_action,
    prepare_tool_args,
)

class LazyAdapterProxy:
    def __init__(self, import_path: str, object_name: str):
        self._import_path = import_path
        self._object_name = object_name

    def __getattr__(self, name: str):
        import importlib
        module = importlib.import_module(self._import_path)
        concrete = getattr(module, self._object_name)
        return getattr(concrete, name)

memory = LazyAdapterProxy("app.adapters.memory", "memory")
vector_memory = LazyAdapterProxy("app.adapters.memory", "vector_memory")
bridge = LazyAdapterProxy("app.adapters.alfonso_bridge", "bridge")

def extract_json_robust(raw: str) -> dict | None:
    from app.adapters.llm_client import extract_json_robust as concrete
    return concrete(raw)

from app.utils.logger import (
    attach_request_id,
    error_logger,
    orchestrator_logger,
)

_TOOL_TIMEOUT = 300

_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
}

from app.domain.services.intent_parser import (
    normalize_message,
    force_tool,
)

_normalize_message = normalize_message
_force_tool = force_tool

def _extract_tool_and_args(data):
    if not isinstance(data, dict):
        return None, {}

    if "tool" in data:
        return data["tool"], data.get("args", {})

    key = next(iter(data), None)
    if key:
        value = data[key]
        if isinstance(value, dict):
            return key, value.get("args", {})

    return None, {}

def _check_and_store_fact(user_message: str, session_id: str, client_id: str | None = None, vector_memory_port=None) -> bool:
    msg_lower = user_message.lower()
    patterns = [
        "recuerda que",
        "guarda que",
        "mi favorito es",
        "mi favorita es",
        "me gusta",
        "tengo un",
        "vivo en",
        "mi nombre es",
        "me llamo",
    ]
    if any(p in msg_lower for p in patterns):
        cleaned_fact = user_message
        for p in ["recuerda que", "guarda que"]:
            if msg_lower.startswith(p):
                cleaned_fact = user_message[len(p):].strip()
                break
        if vector_memory_port is None:
            from app.adapters.memory import vector_memory as vector_memory_port
        vector_memory_port.add_fact(session_id, cleaned_fact, client_id=client_id)
        return True
    return False


# ==============================================================================
# SERVICIOS COMPONENTIZADOS (Responsabilidad Única)
# ==============================================================================

class ConversationContextService:
    """Responsabilidad: Clasificación de tipos de consulta, logs de corrección y ensamblado de contexto semántico."""
    def __init__(self, memory: MemoryPort, vector_memory: VectorMemoryPort):
        self.memory = memory
        self.vector_memory = vector_memory

    async def classify_and_log_corrections(self, user_message: str, session_id: str | None, client_id: str | None, request_id: str | None, logger, error) -> bool:
        is_persistent = True
        msg_lower = user_message.lower()

        ephemeral_keywords = [
            "qué hora es", "que hora es", "dime la hora", "temperatura", "termostato",
            "sube el", "baja el", "enciende", "apaga", "pon música", "pon musica",
            "clima hoy", "tiempo hoy", "qué día es hoy", "que dia es hoy"
        ]
        
        project_keywords = [
            "proyecto", "investiga", "investigar", "programa", "programar", 
            "escribe codigo", "escribe código", "diseña", "diseño", "plano", "pieza"
        ]

        if any(kw in msg_lower for kw in ephemeral_keywords):
            is_persistent = False
            logger.info("Conversación clasificada como EFÍMERA debido a palabras clave cotidianas/domótica.")
        elif session_id:
            existing_meta = self.memory.get_metadata(session_id)
            if existing_meta:
                is_persistent = existing_meta["is_persistent"]
            else:
                is_project = any(kw in msg_lower for kw in project_keywords) or len(user_message.split()) > 10
                is_persistent = is_project
                
                if is_persistent:
                    words = user_message.split()
                    title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
                    discipline = "código/desarrollo" if "programa" in msg_lower or "código" in msg_lower else "general"
                    self.memory.upsert_metadata(session_id, title=title, discipline=discipline, project_name="default", is_persistent=True)
                    logger.info("Nueva conversación persistente iniciada y guardada en metadatos: %s", title)

        corrections_keywords = ["incorrecto", "mal", "error", "corregir", "corrige", "falso", "alucinando", "alucinacion", "no es asi", "no es así", "no es cierto"]
        if any(kw in user_message.lower() for kw in corrections_keywords):
            try:
                import time
                from pathlib import Path
                logs_dir = Path("logs")
                logs_dir.mkdir(exist_ok=True)
                corr_log = logs_dir / "user_corrections.log"
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S") + ",000"
                with open(corr_log, "a", encoding="utf-8") as f:
                    f.write(f"{timestamp} | WARNING | orchestrator | [{request_id or 'sys'}] Corrección del usuario: {user_message}\n")
            except Exception as e:
                error.warning("No se pudo escribir en user_corrections.log: %s", e)

        return is_persistent

    async def build_context(self, user_message: str, session_id: str | None, client_id: str | None) -> tuple[str | None, list[str], list[str]]:
        _check_and_store_fact(user_message, session_id, client_id=client_id, vector_memory_port=self.vector_memory)

        if session_id:
            self.memory.add_message(session_id, "user", user_message, client_id=client_id)

        general_facts = self.vector_memory.query_facts(user_message, limit=3, client_id=client_id)
        
        style_queries = ["estilo de respuesta", "preferencia de formato", "personalidad de Alfonso"]
        style_facts = []
        for q in style_queries:
            results = self.vector_memory.query_facts(q, limit=2, client_id=client_id)
            for fact in results:
                if fact not in style_facts:
                    style_facts.append(fact)
        
        memory_parts = []
        if style_facts:
            memory_parts.append("[Directrices de estilo preferidas por el usuario:]")
            for fact in style_facts:
                memory_parts.append(f"- {fact}")
            memory_parts.append("")
            
        filtered_general = [f for f in general_facts if f not in style_facts]
        if filtered_general:
            memory_parts.append("[Recuerdos semánticos relevantes del usuario:]")
            for fact in filtered_general:
                memory_parts.append(f"- {fact}")
            memory_parts.append("")
            
        if session_id:
            session_summary = self.memory.get_summary(session_id, client_id=client_id)
            if session_summary:
                memory_parts.append("[Historial de la conversación reciente:]")
                memory_parts.append(session_summary)
                
        memory_text = "\n".join(memory_parts) if memory_parts else None
        return memory_text, style_facts, filtered_general


class SpecializedAgentRouter:
    """Responsabilidad: Enrutamiento directo a subagentes de dominio específico (Marcos, DevAgent, CyberSecurityAgent)."""
    def __init__(self, memory: MemoryPort):
        self.memory = memory

    async def route_if_applicable(self, user_message: str, session_id: str | None, client_id: str | None, logger) -> dict | None:
        msg_lower = user_message.lower()
        
        is_marcos_query = "marcos" in msg_lower or any(kw in msg_lower for kw in [
            "codigo civil", "código civil", "codigo penal", "código penal",
            "constitucion española", "constitucion espanola", "constitución española",
            "asesoria legal", "asesoría legal", "consulta juridica", "consulta jurídica"
        ])

        is_dev_query = any(kw in msg_lower for kw in [
            "crea una app", "crea un app", "crear app", "crear aplicación", "crear aplicacion",
            "crea un programa", "crea programa", "escribe codigo", "escribe código", "escribir codigo", "escribir código",
            "escribe el código", "escribe el codigo", "escribir el código", "escribir el codigo", "código html", "codigo html",
            "genera código", "genera codigo", "generar codigo", "generar código", "sandbox", "compila", "compilar", "desarrolla", "desarrollar"
        ]) or ("marcosdev" in msg_lower or "ingeniero de software" in msg_lower or "devagent" in msg_lower)

        is_security_query = any(kw in msg_lower for kw in [
            "ciberseguridad", "cybersecurity", "seguridad", "security", "vulnerabilidad", 
            "vulnerabilities", "auditoría de seguridad", "auditoria de seguridad", "hack",
            "phishing", "malware", "firewall", "puerto", "risk", "riesgo", "alerta de seguridad"
        ]) or ("cyberagent" in msg_lower or "agente de seguridad" in msg_lower or "securityagent" in msg_lower)

        if is_marcos_query:
            logger.info("Consulta de tipo legal. Delegando a MarcosAgent.")
            from app.domain.agents.marcos.marcos_agent import marcos_agent
            response = await marcos_agent.generate_response(user_message)
            if session_id:
                self.memory.add_message(session_id, "assistant", response, client_id=client_id)
            return {
                "type": "chat",
                "response": response,
            }

        if is_dev_query:
            logger.info("Consulta de desarrollo. Delegando a DevAgent.")
            from app.domain.agents.dev.dev_agent import dev_agent
            response = await dev_agent.generate_response(user_message)
            
            if "escritorio" in msg_lower or "desktop" in msg_lower:
                try:
                    import os
                    from pathlib import Path
                    from app.tools.server.filesystem_tools import _resolve_path
                    from app.utils.paths import get_client_desktop
                    desktop_dir = get_client_desktop(client_id)
                    sandbox_path = Path("data/dev_sandbox")
                    if sandbox_path.exists():
                        subfolder = None
                        m_sub = re.search(r"\b(?:carpeta\s+que\s+se\s+llame|carpeta\s+llamada|subcarpeta\s+llamada|directorio\s+llamado|carpeta)\s+([a-zA-Z0-9_\-]+)", msg_lower)
                        if m_sub:
                            subfolder = m_sub.group(1).strip()
                            
                        for entry in os.scandir(sandbox_path):
                            if entry.is_file():
                                file_content = Path(entry.path).read_text(encoding="utf-8")
                                if subfolder:
                                    dest_path = f"{desktop_dir}/{subfolder}/{entry.name}"
                                else:
                                    dest_path = f"{desktop_dir}/{entry.name}"
                                resolved_dest = _resolve_path(dest_path)
                                resolved_dest.parent.mkdir(parents=True, exist_ok=True)
                                logger.info(f"Copiando archivo del sandbox al escritorio: {entry.name} -> {resolved_dest}")
                                resolved_dest.write_text(file_content, encoding="utf-8")
                except Exception as e:
                    logger.error(f"Error al copiar archivos del sandbox al escritorio: {e}")

            if session_id:
                self.memory.add_message(session_id, "assistant", response, client_id=client_id)
            return {
                "type": "chat",
                "response": response,
            }

        if is_security_query:
            logger.info("Consulta de seguridad. Delegando a CyberSecurityAgent.")
            from app.domain.agents.security.security_agent import security_agent
            response = await security_agent.generate_response(user_message)
            if session_id:
                self.memory.add_message(session_id, "assistant", response, client_id=client_id)
            return {
                "type": "chat",
                "response": response,
            }

        return None


class ToolExecutionEngine:
    """Responsabilidad: Control del ciclo de ejecución, control de acceso RBAC y validación sintáctica de código."""
    def __init__(self, memory: MemoryPort, bridge: BridgePort):
        self.memory = memory
        self.bridge = bridge

    async def execute_tool(self, tool_name: str, args: dict, session_id: str | None, client_id: str | None, request_id: str | None, logger, error) -> dict:
        if is_client_tool(tool_name):
            logger.info("Ejecutando tool de cliente: %s", tool_name)
            action = get_client_action(tool_name)
            result = await self.bridge.send_command(action, args, client_id=client_id)
            
            if not isinstance(result, dict) or result.get("status") == "error":
                error.warning("Tool de cliente falló: %s -> %s", tool_name, result)
                return {
                    "status": "error",
                    "execution": "client",
                    "result": result,
                    "message": result.get("error", "Error en ejecución de cliente") if isinstance(result, dict) else "Respuesta vacía de cliente"
                }
            return {
                "status": "ok",
                "execution": "client",
                "result": result,
            }
        else:
            role = "admin"
            if client_id:
                client_meta = self.bridge._client_info_dict.get(client_id)
                if client_meta:
                    role = client_meta.get("role", "guest")
                else:
                    from app.config import settings
                    role = settings.get_client_role(client_id)
            
            if role in ("guest", "limitado") and tool_name != "no_op":
                logger.warning("Acceso denegado: el cliente %s con rol %s intentó ejecutar %s", client_id, role, tool_name)
                return {
                    "status": "rbac_error",
                    "execution": "server",
                    "message": f"Acceso denegado: el rol '{role}' no tiene permisos para ejecutar la herramienta de servidor '{tool_name}'",
                }

            logger.info("Ejecutando tool de servidor: %s", tool_name)
            tool = get_tool(tool_name, request_id)

            if not tool:
                return {
                    "status": "missing_error",
                    "execution": "server",
                    "message": f"No existe {tool_name}",
                }

            validation_res = prepare_tool_args(tool_name, args, request_id)
            if not validation_res.ok:
                error.warning("Validación de argumentos falló para %s: %s", tool_name, validation_res.error)
                return {
                    "status": "validation_error",
                    "execution": "server",
                    "message": validation_res.error,
                }
            args = validation_res.args

            try:
                sig = inspect.signature(tool)
                if "session_id" in sig.parameters:
                    args["session_id"] = session_id or "global"
                if "client_id" in sig.parameters:
                    args["client_id"] = client_id
            except Exception as e:
                logger.warning("No se pudo inspeccionar la firma: %s", e)

            try:
                if asyncio.iscoroutinefunction(tool):
                    result = await asyncio.wait_for(tool(**args), timeout=_TOOL_TIMEOUT)
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(loop.run_in_executor(None, lambda: tool(**args)), timeout=_TOOL_TIMEOUT)
            except Exception as e:
                error.exception("Error ejecutando tool de servidor: %s", tool_name)
                return {
                    "status": "execution_error",
                    "execution": "server",
                    "message": str(e),
                }

            # Validación de sintaxis local en archivos Python
            if tool_name in ("create_file", "append_file", "replace_file_content") and isinstance(result, dict) and result.get("status") == "ok":
                file_path = args.get("path")
                if file_path and str(file_path).endswith(".py"):
                    try:
                        import py_compile
                        from app.tools.server.filesystem_tools import _resolve_path
                        resolved_path = _resolve_path(str(file_path))
                        if resolved_path.exists():
                            py_compile.compile(str(resolved_path), doraise=True)
                            logger.info("Validación sintáctica exitosa para: %s", file_path)
                    except py_compile.PyCompileError as py_err:
                        error_msg = f"Error de sintaxis de Python: {py_err.msg.strip()}"
                        logger.warning("Validación sintáctica falló: %s", error_msg)
                        result = {
                            "status": "error",
                            "message": f"El archivo se guardó pero tiene errores de sintaxis: {error_msg}"
                        }
                    except Exception as e:
                        logger.warning("No se pudo validar la sintaxis: %s", e)

            if isinstance(result, dict) and result.get("status") == "error":
                error.warning("Tool de servidor falló: %s -> %s", tool_name, result)
                return {
                    "status": "error",
                    "execution": "server",
                    "message": result.get("message", "Error ejecutando tool"),
                    "result": result,
                }

            return {
                "status": "ok",
                "execution": "server",
                "result": result,
            }


# ==============================================================================
# PLANNER ORCHESTRATOR (Coordinador)
# ==============================================================================

class PlannerOrchestrator:
    """
    Pipeline único de Alfonso: No hay EventBus ni AgentRegistry.
    PlannerOrchestrator coordina el ciclo de vida delegando a servicios específicos
    de Contexto, Enrutamiento de Agentes y Motor de Ejecución.
    """

    def __init__(
        self,
        llm: LLMPort | None = None,
        memory_port: MemoryPort | None = None,
        vector_memory_port: VectorMemoryPort | None = None,
        bridge_port: BridgePort | None = None,
        calendar_port: CalendarPort | None = None
    ):
        self._llm = llm
        self._memory = memory_port
        self._vector_memory = vector_memory_port
        self._bridge = bridge_port
        self._calendar = calendar_port

        self.context_service = ConversationContextService(self.memory, self.vector_memory)
        self.agent_router = SpecializedAgentRouter(self.memory)
        self.execution_engine = ToolExecutionEngine(self.memory, self.bridge)

    @property
    def llm(self):
        if self._llm is not None:
            return self._llm
        from app.adapters.llm_client import OllamaClient
        return OllamaClient()

    @property
    def memory(self):
        if self._memory is not None:
            return self._memory
        global memory
        return memory

    @property
    def vector_memory(self):
        if self._vector_memory is not None:
            return self._vector_memory
        global vector_memory
        return vector_memory

    @property
    def bridge(self):
        if self._bridge is not None:
            return self._bridge
        global bridge
        return bridge

    @property
    def calendar(self):
        if self._calendar is not None:
            return self._calendar
        from app.adapters.calendar_db import SQLiteCalendarAdapter
        return SQLiteCalendarAdapter()

    async def run(self, user_message, llm=None, request_id=None, session_id=None, client_id=None):
        llm = llm or self.llm
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run() — request_id=%s, session_id=%s, client_id=%s", request_id, session_id, client_id)
        user_message = _normalize_message(user_message)

        # 1. Clasificación y persistencia
        await self.context_service.classify_and_log_corrections(
            user_message, session_id, client_id, request_id, logger, error
        )

        # 2. Ensamblado de Contexto
        memory_text, style_facts, filtered_general = await self.context_service.build_context(
            user_message, session_id, client_id
        )

        # 3. Enrutamiento directo a agentes
        routed = await self.agent_router.route_if_applicable(user_message, session_id, client_id, logger)
        if routed:
            return routed

        # 4. Inferencia con LLM
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
            memory=memory_text,
            client_id=client_id,
        )
        logger.info("Raw LLM output: %s", repr(raw))

        data = extract_json_robust(raw)
        
        # Si no se detectó JSON estructurado de tool, devolver como conversación (chat)
        if not data or "tool" not in data:
            logger.info("Respuesta clasificada como conversacional.")
            if session_id:
                self.memory.add_message(session_id, "assistant", raw, client_id=client_id)
            return {
                "type": "chat",
                "response": raw,
            }

        # 5. Ejecución secuencial de herramientas (con reintento de autocorrección)
        tool_name, args = _extract_tool_and_args(data)
        max_attempts = 3
        current_attempt = 1
        result = None
        execution = "server"

        while current_attempt <= max_attempts:
            logger.info("Ciclo de ejecución de tool: Intento %d de %d", current_attempt, max_attempts)

            if current_attempt > 1:
                # Re-generar contexto e inferencia
                memory_text, _, _ = await self.context_service.build_context(user_message, session_id, client_id)
                raw = await llm.generate(
                    user_message,
                    mode="tool",
                    request_id=request_id,
                    memory=memory_text,
                    client_id=client_id,
                )
                logger.info("Raw LLM output (Intento %d): %s", current_attempt, repr(raw))
                data = extract_json_robust(raw)
                if not data or "tool" not in data:
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "message": "JSON de herramienta inválido tras reintentos",
                            "raw": raw,
                        }
                    current_attempt += 1
                    continue
                tool_name, args = _extract_tool_and_args(data)

            if not tool_name:
                if current_attempt == max_attempts:
                    return {
                        "type": "error",
                        "message": "Herramienta no especificada o desconocida",
                    }
                if session_id:
                    self.memory.add_message(session_id, "system", f"Error: No se pudo identificar la herramienta del JSON: {data}.", client_id=client_id)
                current_attempt += 1
                continue

            # Delegar ejecución al motor
            exec_res = await self.execution_engine.execute_tool(
                tool_name, args, session_id, client_id, request_id, logger, error
            )

            # Manejar estados de error del motor
            status = exec_res.get("status")
            if status in ("rbac_error", "missing_error", "validation_error", "execution_error") or status == "error":
                if current_attempt == max_attempts:
                    return {
                        "type": "error",
                        "execution": exec_res.get("execution", "server"),
                        "tool": tool_name,
                        "message": exec_res.get("message", "Fallo al ejecutar herramienta"),
                        "result": exec_res.get("result"),
                    }
                if session_id:
                    import json
                    self.memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
                    self.memory.add_message(session_id, "system", f"Tool output: {json.dumps(exec_res)}. Corrige parámetros y reintenta.", client_id=client_id)
                current_attempt += 1
                continue

            result = exec_res.get("result")
            execution = exec_res.get("execution")
            break

        # Registrar éxito en memoria
        if session_id:
            import json
            self.memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
            self.memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}", client_id=client_id)

        # Respuestas con confirmación unificada
        if tool_name in _DIRECT_CONFIRM:
            confirm_text = _DIRECT_CONFIRM[tool_name]
            if session_id:
                self.memory.add_message(session_id, "assistant", confirm_text, client_id=client_id)
            return {
                "type": "chat",
                "response": confirm_text,
            }

        logger.info("Ejecución de tool finalizada: %s (%s)", tool_name, execution)
        return {
            "type": "tool",
            "execution": execution,
            "tool": tool_name,
            "args": args,
            "result": result,
        }