from __future__ import annotations

import asyncio
import inspect
import re

from app.core.intent_router import IntentRouter
from app.core.llm_client import extract_json_robust
from app.core.memory import memory
from app.core.vector_memory import vector_memory

from app.core.tool_registry import (
    get_tool,
    is_client_tool,
    get_client_action,
    prepare_tool_args,
)

from app.core.alfonso_bridge import bridge

from app.utils.logger import (
    attach_request_id,
    error_logger,
    orchestrator_logger,
)


_router = IntentRouter()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_TOOL_TIMEOUT = 30


_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
}


FORCE_TOOL_KEYWORDS = [
    "abre",
    "open",
    "lanza",
    "ejecuta",
    "click",
    "escribe",
    "escriba",
    "escribir",
    "escribas",
    "añade",
    "añada",
    "añde",
    "anade",
    "añadi",
    "añadir",
    "anadir",
    "añadas",
    "anada",
    "agrega",
    "agregar",
    "agregue",
    "ponga",
    "poner",
    "navega",
    "visita",
    "crea",
    "crear",
    "borra",
    "borrar",
    "borar",
    "elimina",
    "elmina",
    "elminar",
    "suprime",
    "suprimir",
    "cierra",
    "cerrar",
    "renombra",
    "renombrar",
    "cambia",
    "cambiar",
    "cambiae",
    "cambiá",
]


def _normalize_message(msg):
    
    return _TRAILING_PUNCT_RE.sub("", msg.strip())


def _force_tool(msg):
    
    msg = msg.lower()
    return any(x in msg for x in FORCE_TOOL_KEYWORDS)


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


def _check_and_store_fact(user_message: str, session_id: str) -> bool:
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
        vector_memory.add_fact(session_id, cleaned_fact)
        return True
    return False

def find_base_path_in_history(folder_name: str, history: list) -> str | None:
    # Buscar patrones de ruta que terminen en folder_name o folder_name/ en la sesión actual
    pattern = re.compile(rf"((?:[a-zA-Z]:|/mnt/[a-z]/Users/[^/]+|/home/[^/]+)/[^ ]+/{re.escape(folder_name)})", re.IGNORECASE)
    for msg in history:
        content = msg.get("content", "")
        m = pattern.search(content.replace("\\", "/"))
        if m:
            return m.group(1)
    return None


def parse_file_operation_directly(msg: str, client_info: dict | None, history: list) -> dict | None:
    msg_clean = msg.strip()
    
    # Obtener rutas de base
    home = "C:/Users/luisd"
    desktop = "C:/Users/luisd/Desktop"
    if isinstance(client_info, dict):
        home = client_info.get("home", home).replace("\\", "/")
        desktop = f"{home}/Desktop"
        
    def is_likely_path(p: str) -> bool:
        return "/" in p or "\\" in p or "." in p or p.startswith("~") or p.startswith("C:") or p.startswith("c:")

    def resolve_path(p: str) -> str:
        p = p.strip().replace("\\", "/")
        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
            p = p[1:-1].strip()
            
        parts = p.split("/")
        if len(parts) > 1:
            base_folder = parts[0]
            base_path = find_base_path_in_history(base_folder, history)
            if base_path:
                remainder = "/".join(parts[1:])
                return f"{base_path}/{remainder}"
                
        if re.match(r"^[a-zA-Z]:", p) or p.startswith("/") or p.startswith("~"):
            return p
            
        # Si es un nombre de archivo plano y no contiene barras de ruta, resolverlo bajo el último directorio operativo del historial
        if "/" not in p and "\\" not in p:
            last_folder = None
            for h in reversed(history):
                try:
                    import json
                    h_data = json.loads(h.get("content", ""))
                    tool_args = h_data.get("args", {})
                    path_val = tool_args.get("path", "")
                    if path_val:
                        path_val = path_val.replace("\\", "/")
                        # Si la herramienta anterior creó una carpeta, la usamos de base
                        if h_data.get("tool") in ("create_directory",):
                            last_folder = path_val
                            break
                        # Si fue un archivo, extraemos su carpeta contenedora
                        elif "/" in path_val:
                            last_folder = "/".join(path_val.split("/")[:-1])
                            break
                except Exception:
                    pass
            if last_folder:
                return f"{last_folder}/{p}"

        if "escritorio" in msg.lower() or "desktop" in msg.lower():
            return f"{desktop}/{p}"
        return f"{home}/{p}"

    # 1. RENAME FILE/FOLDER
    # Estructura directa: "renombra X a Y" o "cambia el nombre de X a Y"
    m = re.search(r"\b(?:renombra|renombrá|cambia|cambiar|cambiae)\s+(?:el\s+nombre\s+de\s+|el\s+archivo\s+|la\s+carpeta\s+)?(\S+)\s+(?:a|por)\s+(\S+)", msg_clean, re.IGNORECASE)
    if not m:
        # Estructura pasiva/descriptiva: "el archivo que se llama X cambiae el nombre a Y"
        m = re.search(r"\b(?:el\s+archivo\s+)?(?:dentro\s+de\s+\S+\s+)?(?:que\s+se\s+llama\s+)?(\S+)\s+(?:cambia|cambiae|renombra|cambiá)\s+(?:el\s+nombre\s+)?(?:a|por)\s+(\S+)", msg_clean, re.IGNORECASE)
        
    if m:
        src = m.group(1)
        if is_likely_path(src):
            src_res = resolve_path(src)
            dst_raw = m.group(2).strip().replace("\\", "/")
            new_name = dst_raw.split("/")[-1]
            return {"tool": "rename_file", "args": {"path": src_res, "new_name": new_name}}

    # 2. READ FILE (lee el archivo <path>)
    m = re.search(r"\b(?:lee|leé)\s+(?:el\s+archivo\s+|contenido\s+de\s+)?(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "read_file", "args": {"path": resolve_path(path)}}

    # 3. DELETE FILE (elimina el archivo <path>)
    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar|suprime)\s+el\s+archivo\s+(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "delete_file", "args": {"path": resolve_path(path)}}

    # 4. DELETE DIRECTORY (elimina la carpeta <path>)
    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar)\s+la\s+carpeta\s+(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "delete_directory", "args": {"path": resolve_path(path)}}

    # 5. CREATE DIRECTORY (crea una carpeta llamada <name> en el escritorio)
    m = re.search(r"\bcrea\s+(?:una\s+carpeta\s+|un\s+directorio\s+)(?:de\s+mi\s+|en\s+mi\s+|en\s+el\s+)?(?:escritorio|desktop)?\s*(?:que\s+se\s+llame\s+|llamada\s+|llamado\s+)?([a-zA-Z0-9_\-\s]+)", msg_clean, re.IGNORECASE)
    if m:
        folder_name = m.group(1).strip()
        # Limpiar sufijos que se hayan podido colar en la captura
        folder_name = re.sub(r"\s+(?:en\s+mi\s+|en\s+el\s+|de\s+mi\s+)?(?:escritorio|desktop)$", "", folder_name, flags=re.IGNORECASE).strip()
        if "escritorio" in msg_clean.lower() or "desktop" in msg_clean.lower():
            res_path = f"{desktop}/{folder_name}"
        else:
            res_path = f"{home}/{folder_name}"
        return {"tool": "create_directory", "args": {"path": res_path}}

    # 6. DELETE/READ/WRITE CON RESOLUCIÓN DINÁMICA DE EXTENSIONES (elimina el archivo X de la carpeta Y)
    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar|suprime|lee|muestra)\s+el\s+archivo\s+(\S+)\s+(?:de\s+la\s+carpeta\s+|de\s+|en\s+la\s+carpeta\s+|en\s+)(\S+)", msg_clean, re.IGNORECASE)
    if m:
        filename = m.group(1).strip()
        folder = m.group(2).strip()
        folder_res = resolve_path(folder)
        
        final_filename = filename
        try:
            import os
            # Mapear ruta de Windows en WSL si aplica
            check_path = folder_res
            if check_path.startswith("C:/") or check_path.startswith("c:/"):
                check_path = "/mnt/" + check_path[0].lower() + check_path[2:]
            
            if os.path.isdir(check_path):
                for f in os.listdir(check_path):
                    if os.path.splitext(f)[0].lower() == filename.lower():
                        final_filename = f
                        break
        except Exception:
            pass
            
        final_path = f"{folder_res}/{final_filename}"
        action = "delete_file" if any(x in msg_clean.lower() for x in ["elimina", "elmina", "borra"]) else "read_file"
        return {"tool": action, "args": {"path": final_path}}

    # 7. APPEND DETERMINISTA (añade a X Y / al archivo X añade Y)
    # Caso A: "añade a [archivo] [contenido]" (soportando erratas como añde / anade)
    m = re.search(r"\b(?:añade|añde|anade|agrega|escribe|escribir)\s+(?:a\s+|en\s+)(?:el\s+archivo\s+)?(\S+)\s+(.+)", msg_clean, re.IGNORECASE)
    if not m:
        # Caso B: "al archivo [archivo] añade/escribe [contenido]"
        m = re.search(r"\bal\s+archivo\s+(\S+)\s+(?:añade|añde|anade|agrega|escribe)\s+(.+)", msg_clean, re.IGNORECASE)
        
    if m:
        filename = m.group(1).strip()
        content = m.group(2).strip()
        return {"tool": "append_file", "args": {"path": resolve_path(filename), "content": content}}

    # 8. CREATE FILE DETERMINISTA (crea el archivo X que diga Y / dentro de esta carpeta crea un archivo X que diga Y)
    m = re.search(r"\b(?:crea|escribir|escribe)\s+(?:un\s+archivo\s+|el\s+archivo\s+)?(\S+)\s+(?:que\s+diga|con\s+contenido)\s+(.+)", msg_clean, re.IGNORECASE)
    if m:
        filename = m.group(1).strip()
        content = m.group(2).strip()
        
        folder = None
        if any(x in msg_clean.lower() for x in ["esta carpeta", "este directorio", "esa carpeta"]):
            for h in reversed(history):
                try:
                    import json
                    h_data = json.loads(h.get("content", ""))
                    if h_data.get("tool") in ("create_directory",):
                        folder = h_data.get("args", {}).get("path")
                        break
                except Exception:
                    pass
        if not folder:
            if "escritorio" in msg_clean.lower() or "desktop" in msg_clean.lower():
                folder = desktop
            else:
                folder = home
                
        final_path = f"{folder}/{filename}" if folder else resolve_path(filename)
        return {"tool": "create_file", "args": {"path": final_path, "content": content}}

    return None
class PlannerOrchestrator:
    """
    Pipeline único de Alfonso (post Fase 2): no hay EventBus ni AgentRegistry.
    Todo pasa por aquí — detección de intent, llamada al LLM, ejecución de
    tool (cliente vía bridge o servidor vía tool_registry) y, si aplica,
    persistencia en la memoria corta de Fase 1 (SessionMemory).
    """

    async def run(self, user_message, llm, request_id=None, session_id=None):
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run() — request_id=%s, session_id=%s", request_id, session_id)
        user_message = _normalize_message(user_message)

        # Guardar hechos en la memoria vectorial si aplica (Fase 4)
        _check_and_store_fact(user_message, session_id)

        # Persistimos el turno del usuario en memoria corta ANTES de generar,
        # sea cual sea el intent. Así un mensaje "tool" también queda en el
        # historial que un futuro turno "chat" podrá recuperar como contexto.
        if session_id:
            memory.add_message(session_id, "user", user_message)

        # Consultar recuerdos semánticos relevantes (Fase 4)
        # 1. Buscar datos generales/personales relevantes al mensaje
        general_facts = vector_memory.query_facts(user_message, limit=3)
        
        # 2. Buscar explícitamente directrices de estilo conversacional y preferencias de formato
        style_queries = ["estilo de respuesta", "preferencia de formato", "personalidad de Alfonso"]
        style_facts = []
        for q in style_queries:
            results = vector_memory.query_facts(q, limit=2)
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
            session_summary = memory.get_summary(session_id)
            if session_summary:
                memory_parts.append("[Historial de la conversación reciente:]")
                memory_parts.append(session_summary)
                
        memory_text = "\n".join(memory_parts) if memory_parts else None

        router = _router.detect_with_detail(user_message)

        # ------------------------------------------------------------
        # CHAT
        # ------------------------------------------------------------
        if router["intent"] == "chat" and not _force_tool(user_message):
            logger.info("Intent detectado: chat (no se fuerza tool)")

            response = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
            )

            if session_id:
                memory.add_message(session_id, "assistant", response)

            return {
                "type": "chat",
                "response": response,
            }

        # ------------------------------------------------------------
        # DETECCION DE TOOL DIRECTA (DETERMINISTA)
        # ------------------------------------------------------------
        history_msgs = memory.get_history(session_id) if session_id else []
        direct_tool = parse_file_operation_directly(user_message, bridge.client_info, history_msgs)
        
        if direct_tool:
            tool_name = direct_tool["tool"]
            args = direct_tool["args"]
            logger.info("Filtro determinista: detectada tool %s con args %s", tool_name, args)
        else:
            # ------------------------------------------------------------
            # TOOL — parseo de la respuesta del LLM en modo tool
            # ------------------------------------------------------------
            raw = await llm.generate(
                user_message,
                mode="tool",
                request_id=request_id,
                memory=memory_text,
            )
            logger.info("Raw LLM output: %s", repr(raw))

            data = extract_json_robust(raw)
            logger.info("LLM tool response: %s", data)
            if not data:
                error.warning("LLM no devolvió JSON de tool válido")
                return {
                    "type": "error",
                    "message": "JSON tool inválido",
                    "raw": raw,
                }

            tool_name, args = _extract_tool_and_args(data)

            if not tool_name:
                return {
                    "type": "error",
                    "message": "Tool desconocida",
                }

        # ------------------------------------------------------------
        # EJECUCIÓN — cliente (bridge) o servidor (tool_registry)
        # ------------------------------------------------------------
        if is_client_tool(tool_name):
            logger.info("Ejecutando tool de cliente: %s", tool_name)
            action = get_client_action(tool_name)
            logger.info("Enviando al cliente %s", action)

            result = await bridge.send_command(action, args)

            if not isinstance(result, dict) or result.get("status") == "error":
                error.warning(
                    "Tool de cliente falló: %s -> %s",
                    tool_name,
                    result,
                )
                return {
                    "type": "error",
                    "execution": "client",
                    "tool": tool_name,
                    "message": (
                        result.get("error", "Error desconocido ejecutando tool en el cliente")
                        if isinstance(result, dict)
                        else "Respuesta inválida del cliente"
                    ),
                    "result": result,
                }

            execution = "client"

        else:
            logger.info("Ejecutando tool de servidor: %s", tool_name)
            tool = get_tool(tool_name, request_id)

            if not tool:
                return {
                    "type": "error",
                    "message": f"No existe {tool_name}",
                }

            # Validar/Adaptar argumentos usando el esquema de la Fase 1
            validation_res = prepare_tool_args(tool_name, args, request_id)
            if not validation_res.ok:
                error.warning("Validación de argumentos falló para %s: %s", tool_name, validation_res.error)
                return {
                    "type": "error",
                    "message": validation_res.error,
                }
            args = validation_res.args

            # Inyectar session_id si la firma de la función lo requiere
            try:
                sig = inspect.signature(tool)
                if "session_id" in sig.parameters:
                    args["session_id"] = session_id or "global"
            except Exception as e:
                logger.warning("No se pudo inspeccionar la firma de la tool %s: %s", tool_name, e)

            try:
                if asyncio.iscoroutinefunction(tool):
                    result = await asyncio.wait_for(
                        tool(**args),
                        timeout=_TOOL_TIMEOUT,
                    )
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: tool(**args)),
                        timeout=_TOOL_TIMEOUT,
                    )

            except Exception as e:
                error.exception("Error ejecutando tool de servidor: %s", tool_name)
                return {
                    "type": "error",
                    "execution": "server",
                    "tool": tool_name,
                    "message": str(e),
                }

            if isinstance(result, dict) and result.get("status") == "error":
                error.warning(
                    "Tool de servidor falló: %s -> %s",
                    tool_name,
                    result,
                )
                return {
                    "type": "error",
                    "execution": "server",
                    "tool": tool_name,
                    "message": result.get("message", "Error ejecutando tool"),
                    "result": result,
                }

            execution = "server"

        # Registrar llamadas de herramientas y sus resultados en el historial de la sesión para el contexto de Alfonso
        if session_id:
            import json
            memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}))
            memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}")

        # ------------------------------------------------------------
        # RESPUESTA UNIFICADA
        # ------------------------------------------------------------
        if tool_name in _DIRECT_CONFIRM:
            confirm_text = _DIRECT_CONFIRM[tool_name]
            if session_id:
                memory.add_message(session_id, "assistant", confirm_text)
            return {
                "type": "chat",
                "response": confirm_text,
            }

        logger.info("Ejecución de tool finalizada: %s (%s)", tool_name, execution)

        return {
            "type": "tool",
            "execution": execution,
            "tool": tool_name,
            "result": result,
        }