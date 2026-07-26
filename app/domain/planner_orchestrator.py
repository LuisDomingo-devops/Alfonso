"""
PLANNER ORCHESTRATOR — Planificador y orquestador central de Alfonso.

¿QUÉ HACE?
Orquesta y ejecuta el ciclo de vida del planificador (fase de intención, planificación y ejecución de herramientas). Es el pipeline principal por el que pasa cada petición de usuario.

¿CUÁNDO LO HACE?
Se ejecuta en cada llamada al endpoint /chat, procesando el mensaje del usuario y coordinando las interacciones.

¿CÓMO LO HACE?
Analiza la intención de la consulta usando heurísticas para delegar a MarcosAgent o DevAgent. De lo contrario, genera un plan de ejecución de herramientas, las ejecuta de forma secuencial y construye la respuesta final para el usuario.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py: Invoca este orquestador a través de /chat.
- app/domain/agents/dev/dev_agent.py: Delega consultas de desarrollo de software.
- app/domain/agents/marcos/marcos_agent.py: Delega consultas de legislación española.
- app/domain/intent_router.py: Determina la intención inicial del usuario.
- app/adapters/tool_registry.py: Busca y proporciona las herramientas a ejecutar.
"""

from __future__ import annotations

import asyncio
import inspect
import re

from app.domain.intent_router import IntentRouter
from app.domain.ports.llm_port import LLMPort
from app.domain.ports.memory_port import MemoryPort, VectorMemoryPort
from app.domain.ports.bridge_port import BridgePort
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


_router = IntentRouter()

_TOOL_TIMEOUT = 300

_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
}

from app.domain.services.intent_parser import (
    normalize_message,
    force_tool,
    find_base_path_in_history,
    parse_composite_operations,
    parse_calendar_operation_directly,
    parse_mail_operation_directly,
    parse_system_operation_directly,
    parse_memory_operation_directly,
    parse_browser_operation_directly,
    parse_calendar_delete_directly,
    parse_calendar_update_directly,
    parse_calendar_create_directly,
    parse_file_operation_directly,
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

class PlannerOrchestrator:
    """
    Pipeline único de Alfonso (post Fase 2): no hay EventBus ni AgentRegistry.
    Todo pasa por aquí — detección de intent, llamada al LLM, ejecución de
    tool (cliente vía bridge o servidor vía tool_registry) y, si aplica,
    persistencia en la memoria corta de Fase 1 (SessionMemory).
    """

    def __init__(
        self,
        llm: LLMPort | None = None,
        memory: MemoryPort | None = None,
        vector_memory: VectorMemoryPort | None = None,
        bridge: BridgePort | None = None,
        calendar: CalendarPort | None = None
    ):
        self._llm = llm
        self._memory = memory
        self._vector_memory = vector_memory
        self._bridge = bridge
        self._calendar = calendar

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
        memory = self.memory
        vector_memory = self.vector_memory
        bridge = self.bridge
        
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run() — request_id=%s, session_id=%s, client_id=%s", request_id, session_id, client_id)
        user_message = _normalize_message(user_message)

        # ------------------------------------------------------------
        # CLASIFICACIÓN DE CONVERSACIÓN (EFÍMERA VS. PERSISTENTE/PROYECTO)
        # ------------------------------------------------------------
        is_persistent = True
        msg_lower = user_message.lower()

        # Palabras clave y patrones típicamente efímeros (domótica, preguntas rápidas, clima, etc.)
        ephemeral_keywords = [
            "qué hora es", "que hora es", "dime la hora", "temperatura", "termostato",
            "sube el", "baja el", "enciende", "apaga", "pon música", "pon musica",
            "clima hoy", "tiempo hoy", "qué día es hoy", "que dia es hoy"
        ]
        
        # Palabras clave que denotan explícitamente iniciar o trabajar en un proyecto
        project_keywords = [
            "proyecto", "investiga", "investigar", "programa", "programar", 
            "escribe codigo", "escribe código", "diseña", "diseño", "plano", "pieza"
        ]

        if any(kw in msg_lower for kw in ephemeral_keywords):
            is_persistent = False
            logger.info("Conversación clasificada como EFÍMERA debido a palabras clave cotidianas/domótica.")
        elif session_id:
            # Si ya hay metadatos guardados para esta sesión, preservamos el estado actual
            existing_meta = memory.get_metadata(session_id)
            if existing_meta:
                is_persistent = existing_meta["is_persistent"]
            else:
                # Si es una sesión nueva, evaluamos si contiene intención de proyecto/investigación compleja
                is_project = any(kw in msg_lower for kw in project_keywords) or len(user_message.split()) > 10
                is_persistent = is_project
                
                if is_persistent:
                    # Crear automáticamente un título inicial descriptivo
                    words = user_message.split()
                    title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
                    discipline = "código/desarrollo" if "programa" in msg_lower or "código" in msg_lower else "general"
                    memory.upsert_metadata(session_id, title=title, discipline=discipline, project_name="default", is_persistent=True)
                    logger.info("Nueva conversación persistente iniciada y guardada en metadatos: %s", title)

        # Detección de correcciones del usuario (para el módulo BRAIN)
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

        # Guardar hechos en la memoria vectorial si aplica (Fase 4)
        _check_and_store_fact(user_message, session_id, client_id=client_id, vector_memory_port=vector_memory)

        # Persistimos el turno del usuario en memoria corta ANTES de generar
        if session_id:
            memory.add_message(session_id, "user", user_message, client_id=client_id)

        # Consultar recuerdos semánticos relevantes (Fase 4)
        # 1. Buscar datos generales/personales relevantes al mensaje
        general_facts = vector_memory.query_facts(user_message, limit=3, client_id=client_id)
        
        # 2. Buscar explícitamente directrices de estilo conversacional y preferencias de formato
        style_queries = ["estilo de respuesta", "preferencia de formato", "personalidad de Alfonso"]
        style_facts = []
        for q in style_queries:
            results = vector_memory.query_facts(q, limit=2, client_id=client_id)
            for fact in results:
                if fact not in style_facts:
                    style_facts.append(fact)
        
        memory_parts = []
        
        # Inyectar primero la sección específica de estilo
        if style_facts:
            memory_parts.append("[Directrices de estilo preferidas por el usuario:]")
            for fact in style_facts:
                memory_parts.append(f"- {fact}")
            memory_parts.append("")
            
        # Inyectar los recuerdos semánticos generales relevantes
        # Excluimos duplicados que ya estén en estilo
        filtered_general = [f for f in general_facts if f not in style_facts]
        if filtered_general:
            memory_parts.append("[Recuerdos semánticos relevantes del usuario:]")
            for fact in filtered_general:
                memory_parts.append(f"- {fact}")
            memory_parts.append("")
            
        if session_id:
            session_summary = memory.get_summary(session_id, client_id=client_id)
            if session_summary:
                memory_parts.append("[Historial de la conversación reciente:]")
                memory_parts.append(session_summary)
                
        memory_text = "\n".join(memory_parts) if memory_parts else None

        # ------------------------------------------------------------
        # RUTA DIRECTA A AGENTES ESPECIALIZADOS
        # ------------------------------------------------------------
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
                memory.add_message(session_id, "assistant", response, client_id=client_id)
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
                memory.add_message(session_id, "assistant", response, client_id=client_id)
            return {
                "type": "chat",
                "response": response,
            }

        if is_security_query:
            logger.info("Consulta de seguridad. Delegando a CyberSecurityAgent.")
            from app.domain.agents.security.security_agent import security_agent
            response = await security_agent.generate_response(user_message)
            if session_id:
                memory.add_message(session_id, "assistant", response, client_id=client_id)
            return {
                "type": "chat",
                "response": response,
            }

        # ------------------------------------------------------------
        # INFERENCIA Y BUCLE NATIVO DE AGENTES (FUNCTION CALLING)
        # ------------------------------------------------------------
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
            memory=memory_text,
            client_id=client_id,
        )
        logger.info("Raw LLM output: %s", repr(raw))

        data = extract_json_robust(raw)
        
        # Si no detectamos estructura de llamada a herramienta, es un chat directo (conversacional)
        if not data or "tool" not in data:
            logger.info("Respuesta clasificada como conversacional.")
            if session_id:
                memory.add_message(session_id, "assistant", raw, client_id=client_id)
            return {
                "type": "chat",
                "response": raw,
            }

        # Si detectamos una llamada a herramienta, iniciamos bucle de ejecución
        tool_name, args = _extract_tool_and_args(data)
        max_attempts = 3
        current_attempt = 1
        result = None
        execution = "server"
        
        while current_attempt <= max_attempts:
            logger.info("Ciclo de ejecución de tool: Intento %d de %d", current_attempt, max_attempts)
            
            if current_attempt > 1:
                # Re-generar consulta inyectando las alertas de error de la iteración previa
                if session_id:
                    latest_history_parts = []
                    if style_facts:
                        latest_history_parts.append("[Directrices de estilo preferidas por el usuario:]")
                        for fact in style_facts:
                            latest_history_parts.append(f"- {fact}")
                        latest_history_parts.append("")
                    if filtered_general:
                        latest_history_parts.append("[Recuerdos semánticos relevantes del usuario:]")
                        for fact in filtered_general:
                            latest_history_parts.append(f"- {fact}")
                        latest_history_parts.append("")
                    
                    session_summary = memory.get_summary(session_id, client_id=client_id)
                    if session_summary:
                        latest_history_parts.append("[Historial de la conversación reciente:]")
                        latest_history_parts.append(session_summary)
                    
                    memory_text = "\n".join(latest_history_parts) if latest_history_parts else None

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
                    memory.add_message(session_id, "system", f"Error: No se pudo identificar la herramienta del JSON: {data}.", client_id=client_id)
                current_attempt += 1
                continue

            # ------------------------------------------------------------
            # EJECUCIÓN — cliente (bridge) o servidor (tool_registry)
            # ------------------------------------------------------------
            if is_client_tool(tool_name):
                logger.info("Ejecutando tool de cliente: %s", tool_name)
                action = get_client_action(tool_name)
                result = await bridge.send_command(action, args, client_id=client_id)
                
                if not isinstance(result, dict) or result.get("status") == "error":
                    error.warning("Tool de cliente falló (Intento %d): %s -> %s", current_attempt, tool_name, result)
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "execution": "client",
                            "tool": tool_name,
                            "message": result.get("error", "Error desconocido en el agente cliente") if isinstance(result, dict) else "Respuesta inválida del cliente",
                            "result": result,
                        }
                    if session_id:
                        import json
                        memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
                        memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}. Corrige los parámetros y vuelve a intentar.", client_id=client_id)
                    current_attempt += 1
                    continue
                execution = "client"
            else:
                # Control de Acceso (RBAC) para roles restrictivos
                role = "admin"
                if client_id:
                    client_meta = bridge._client_info_dict.get(client_id)
                    if client_meta:
                        role = client_meta.get("role", "guest")
                    else:
                        from app.config import settings
                        role = settings.get_client_role(client_id)
                
                if role in ("guest", "limitado") and tool_name != "no_op":
                    logger.warning("Acceso denegado: el cliente %s con rol %s intentó ejecutar %s", client_id, role, tool_name)
                    return {
                        "type": "error",
                        "message": f"Acceso denegado: el rol '{role}' no tiene permisos para ejecutar la herramienta de servidor '{tool_name}'",
                    }

                logger.info("Ejecutando tool de servidor: %s", tool_name)
                tool = get_tool(tool_name, request_id)

                if not tool:
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "message": f"No existe {tool_name}",
                        }
                    if session_id:
                        memory.add_message(session_id, "system", f"Error: La herramienta de servidor '{tool_name}' no está registrada en el sistema.", client_id=client_id)
                    current_attempt += 1
                    continue

                # Validar/Adaptar argumentos usando los esquemas cargados
                validation_res = prepare_tool_args(tool_name, args, request_id)
                if not validation_res.ok:
                    error.warning("Validación de argumentos falló para %s: %s", tool_name, validation_res.error)
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "message": validation_res.error,
                        }
                    if session_id:
                        memory.add_message(session_id, "system", f"Error de validación de argumentos para '{tool_name}': {validation_res.error}", client_id=client_id)
                    current_attempt += 1
                    continue
                args = validation_res.args

                # Inyectar variables de sesión y cliente si la firma de la función lo permite
                try:
                    sig = inspect.signature(tool)
                    if "session_id" in sig.parameters:
                        args["session_id"] = session_id or "global"
                    if "client_id" in sig.parameters:
                        args["client_id"] = client_id
                except Exception as e:
                    logger.warning("No se pudo inspeccionar firma: %s", e)

                try:
                    if asyncio.iscoroutinefunction(tool):
                        result = await asyncio.wait_for(tool(**args), timeout=_TOOL_TIMEOUT)
                    else:
                        loop = asyncio.get_running_loop()
                        result = await asyncio.wait_for(loop.run_in_executor(None, lambda: tool(**args)), timeout=_TOOL_TIMEOUT)
                except Exception as e:
                    error.exception("Error ejecutando tool de servidor: %s", tool_name)
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "execution": "server",
                            "tool": tool_name,
                            "message": str(e),
                        }
                    if session_id:
                        memory.add_message(session_id, "system", f"Error: La herramienta '{tool_name}' falló con excepción: {str(e)}", client_id=client_id)
                    current_attempt += 1
                    continue

                # Validación de sintaxis local en archivos Python guardados
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
                    error.warning("Tool de servidor falló (Intento %d): %s -> %s", current_attempt, tool_name, result)
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "execution": "server",
                            "tool": tool_name,
                            "message": result.get("message", "Error ejecutando tool"),
                            "result": result,
                        }
                    if session_id:
                        import json
                        memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
                        memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}. Corrige los errores e inténtalo de nuevo.", client_id=client_id)
                    current_attempt += 1
                    continue

                execution = "server"
            
            # Si llegó aquí sin continuar/fallar, salimos del ciclo de reintentos
            break

        # Registrar llamadas de herramientas y sus resultados en el historial de la sesión para el contexto de Alfonso
        if session_id:
            import json
            memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
            memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}", client_id=client_id)

        # ------------------------------------------------------------
        # RESPUESTA UNIFICADA
        # ------------------------------------------------------------
        if tool_name in _DIRECT_CONFIRM:
            confirm_text = _DIRECT_CONFIRM[tool_name]
            if session_id:
                memory.add_message(session_id, "assistant", confirm_text, client_id=client_id)
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