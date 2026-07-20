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
from app.adapters.llm_client import extract_json_robust
from app.adapters.memory import memory, vector_memory

from app.adapters.tool_registry import (
    get_tool,
    is_client_tool,
    get_client_action,
    prepare_tool_args,
)

from app.adapters.alfonso_bridge import bridge

from app.utils.logger import (
    attach_request_id,
    error_logger,
    orchestrator_logger,
)


_router = IntentRouter()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_TOOL_TIMEOUT = 300


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


def _check_and_store_fact(user_message: str, session_id: str, client_id: str | None = None) -> bool:
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
        vector_memory.add_fact(session_id, cleaned_fact, client_id=client_id)
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


def parse_composite_operations(msg: str) -> list | None:
    msg_clean = msg.lower().strip()
    
    # Palabras clave de acción
    open_words = ["abrir", "abre", "muestra", "mostrar", "ver", "pantalla"]
    close_words = ["cerrar", "cierra", "oculta", "ocultar"]
    
    # Identificar a qué se refiere cada acción en la frase
    parts = re.split(r'\by\b|\bpero\b|,', msg_clean)
    tools = []
    
    for part in parts:
        part = part.strip()
        is_open = any(w in part for w in open_words)
        is_close = any(w in part for w in close_words)
        
        has_cal = any(x in part for x in ["calendario", "agenda", "citas"])
        has_mail = any(y in part for y in ["correo", "mail", "email", "recibidos"])
        
        # Si no hay acción específica en esta parte, buscar heredada de la primera parte
        if not is_open and not is_close and parts:
            first_part = parts[0]
            is_open = any(w in first_part for w in open_words)
            is_close = any(w in first_part for w in close_words)
            
        if has_cal:
            if is_open:
                tools.append({"tool": "calendar_open_ui", "args": {}})
            elif is_close:
                tools.append({"tool": "calendar_close_ui", "args": {}})
        if has_mail:
            if is_open:
                tools.append({"tool": "mail_open_ui", "args": {}})
            elif is_close:
                tools.append({"tool": "mail_close_ui", "args": {}})
                
    if len(tools) > 1:
        unique_tools = []
        for t in tools:
            if t not in unique_tools:
                unique_tools.append(t)
        return unique_tools
        
    return None


def parse_calendar_operation_directly(msg: str) -> dict | None:
    from datetime import datetime
    msg_clean = msg.lower().strip()
    if re.search(r"\b(abre|abrir|mostrar|ver)\b.{0,20}\b(el calendario|calendario|citas|agenda)\b", msg_clean):
        return {"tool": "calendar_open_ui", "args": {}}
    if re.search(r"\b(qu[eé] tengo hoy|citas de hoy|agenda de hoy)\b", msg_clean):
        if not any(x in msg_clean for x in ["correo", "mail", "email"]):
            today_str = datetime.now().strftime("%Y-%m-%d")
            return {"tool": "calendar_list_events", "args": {"start_date": today_str, "end_date": today_str}}
    if re.search(r"\b(?:lista|listá|listar|mostrar|muestra|dime|ver|veo)\b.*\b(?:citas|eventos|reuniones|compromisos|calendario|agenda)\b", msg_clean):
        return {"tool": "calendar_list_events", "args": {}}
    if re.search(r"\b(cierra|cerrar|oculta|ocultar)\b.{0,20}\b(el calendario|calendario|citas|agenda)\b", msg_clean):
        return {"tool": "calendar_close_ui", "args": {}}
    return None


def parse_mail_operation_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    
    # 1. Generar/inyectar correos de prueba
    if re.search(r"\b(genera(r)?|crea(r)?|inyecta(r)?|pon(er)?) (correos|mails|emails) (de prueba|simulados)\b", msg_clean):
        return {"tool": "mail_receive_mock_emails", "args": {}}
        
    # 2. Resumen de correos
    if re.search(r"\b(resumen de(l)? (correo|mail)|resume(ir)? los correos|resumen de la mañana|notificaciones de correo|resumen matutino)\b", msg_clean):
        return {"tool": "mail_get_unread_summary", "args": {}}
        
    # 3. Clasificar correos
    if re.search(r"\b(clasifica(r)? (el |los )?(correo|mail|correos|emails))\b", msg_clean):
        return {"tool": "mail_classify_emails", "args": {}}
        
    # 4. Abrir la interfaz gráfica de correo (visual)
    if re.search(r"\b(abrir|abre|muestra|mostrar|ver|pantalla) (el |la |los |las )?(cliente de correo|bandeja de entrada|correo visual|ventana de correo|recibidos|correo|correos|mail|mails|email|emails)\b", msg_clean) or msg_clean in ("abre correo", "abrir correo"):
        return {"tool": "mail_open_ui", "args": {}}

    # 5. Cerrar la interfaz gráfica de correo (visual)
    if re.search(r"\b(cierra|cerrar|oculta|ocultar) (el |la |los |las )?(cliente de correo|bandeja de entrada|correo visual|ventana de correo|recibidos|correo|correos|mail|mails|email|emails)\b", msg_clean):
        return {"tool": "mail_close_ui", "args": {}}

    # 6. Listar correos (resto de casos de lectura general en texto)
    if re.search(r"\b(?:lee|leer|lista|listá|listar|dame|ver|mostrar|muestra)\b.*\b(?:correo|mail|correos|emails|mails)\b", msg_clean):
        return {"tool": "mail_list_emails", "args": {}}
        
    return None


def parse_system_operation_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    # Coincide con preguntas comunes sobre la hora y fecha
    if re.search(r"\b(qu[eé]\s+hora\s+es|dime\s+la\s+hora|qu[eé]\s+hora\s+tienes|fecha\s+de\s+hoy|qu[eé]\s+d[ií]a\s+es\s+hoy|fecha\s+y\s+hora)\b", msg_clean):
        return {"tool": "get_current_datetime", "args": {}}
    if re.search(r"\b(captura\s+de\s+pantalla|toma\s+una\s+captura|pantallazo|hacer\s+captura|hace\s+captura)\b", msg_clean):
        return {"tool": "screenshot", "args": {}}
    if re.search(r"\b(ventanas\s+abiertas|lista\s+las\s+ventanas|mostrar\s+ventanas|ver\s+ventanas)\b", msg_clean):
        return {"tool": "window_list", "args": {}}
    return None


def parse_memory_operation_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    m = re.search(r"\b(?:recuerda\s+que|graba\s+que|memoriza\s+que)\s+(.+)", msg, re.IGNORECASE)
    if m:
        fact = m.group(1).strip()
        return {"tool": "save_user_preference", "args": {"fact": fact}}
    
    if re.search(r"\b(?:mi\s+perfil|mis\s+preferencias|qué\s+recuerdas\s+de\s+mí|que\s+recuerdas\s+de\s+mi|dame\s+mi\s+perfil)\b", msg_clean):
        if not any(x in msg_clean for x in ["elimina", "borra", "quita", "modifica", "cambia"]):
            return {"tool": "get_user_profile", "args": {}}
    
    m_forget = re.search(r"\b(?:olvida\s+que|borra\s+que|olvidar\s+que|borrar\s+que)\s+(.+)", msg, re.IGNORECASE)
    if m_forget:
        query = m_forget.group(1).strip()
        return {"tool": "forget_user_fact", "args": {"query": query}}
        
    return None


def parse_browser_operation_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    # Coincide de forma muy flexible y tolerante a erratas (ej. "pagna"):
    # "abre la pagna elpais.com", "entra en google.es", "navega a marca.com"
    m = re.search(r"\b(?:abre|abrir|navega|navegar|entra|entrar|ir\s+a)\b.*\b([a-zA-Z0-9.\-_/:]+\.[a-zA-Z]{2,6}(?:/[^\s]*)?)", msg_clean, re.IGNORECASE)
    if m:
        url = m.group(1).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return {"tool": "open_url", "args": {"url": url}}
    return None


def parse_calendar_delete_directly(msg: str) -> dict | None:
    from datetime import datetime, timedelta
    from app.adapters.calendar_db import list_events

    msg_clean = msg.lower().strip()
    if not re.search(r"\b(elimina|eliminar|borra|borrar|cancela|cancelar|quita|quitar)\b", msg_clean):
        return None
    if not re.search(r"\b(cita|reunión|reunion|evento|compromiso|citas|reuniones|eventos|compromisos)\b", msg_clean):
        return None

    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    # --- 0. ELIMINAR TODAS LAS CITAS DE UN MES (ej: "elimina todas las citas del mes de julio") ---
    if "todo" in msg_clean or "todas" in msg_clean:
        month_match = re.search(r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_clean)
        if month_match:
            tgt_month_name = month_match.group(1)
            tgt_month_num = months_map[tgt_month_name]
            tgt_year = datetime.now().year
            import calendar
            last_day = calendar.monthrange(tgt_year, tgt_month_num)[1]
            start_date = f"{tgt_year}-{tgt_month_num:02d}-01"
            end_date = f"{tgt_year}-{tgt_month_num:02d}-{last_day:02d}"
            try:
                events = list_events(start_date=start_date, end_date=end_date)
                if events:
                    from app.adapters.calendar_db import delete_event
                    from app.adapters.alfonso_bridge import bridge
                    import asyncio
                    deleted_count = 0
                    for ev in events:
                        if delete_event(ev["id"]):
                            deleted_count += 1
                    if deleted_count > 0:
                        if bridge.has_clients():
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    loop.create_task(bridge.send_command("calendar.sync", {"action": "delete_all"}))
                            except Exception:
                                pass
                        return {
                            "type": "chat",
                            "response": f"Se han eliminado todas las citas del mes de {tgt_month_name} ({deleted_count} en total) correctamente."
                        }
                    else:
                        return {
                            "type": "chat",
                            "response": f"No se pudo eliminar ninguna cita para el mes de {tgt_month_name}."
                        }
                else:
                    return {
                        "type": "chat",
                        "response": f"No hay ninguna cita registrada para el mes de {tgt_month_name}."
                    }
            except Exception as e:
                return {
                    "type": "chat",
                    "response": f"Ocurrió un error al intentar eliminar las citas: {str(e)}"
                }

    # --- 1. INTENTAR ELIMINAR POR ID DIRECTO (ej: "borra la cita con id 2") ---
    if not re.search(r"\b(el|del|de|día|dia)\s+\d+", msg_clean):
        match = re.search(r"\b(?:id|número|núm|nº|evento|cita)\s*(\d+)\b", msg_clean)
        if match:
            event_id = int(match.group(1))
            return {"tool": "calendar_delete_event", "args": {"event_id": event_id}}

    # --- 2. INTENTAR ELIMINAR POR FECHA Y DESCRIPCIÓN (Bypass inteligente) ---
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    date_matched = False

    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    # "el 7 de julio" o "del 7 de julio"
    date_match = re.search(r"\b(?:el|del)\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_clean)
    if date_match:
        day = int(date_match.group(1))
        month = months_map[date_match.group(2)]
        date_matched = True
    else:
        # "el día 7", "del día 7", "el 7", "del 7"
        date_match = re.search(r"\b(?:el|del|de)\s+(?:d[ií]a\s+)?(\d{1,2})\b", msg_clean)
        if date_match:
            day = int(date_match.group(1))
            date_matched = True
        elif "mañana" in msg_clean:
            tomorrow = now + timedelta(days=1)
            year = tomorrow.year
            month = tomorrow.month
            day = tomorrow.day
            date_matched = True
        elif "hoy" in msg_clean:
            date_matched = True

    if not date_matched:
        return None

    date_str = f"{year}-{month:02d}-{day:02d}"

    try:
        events = list_events(start_date=date_str, end_date=date_str)
        if not events:
            return None

        # Si hay exactamente una cita agendada ese día, la eliminamos directamente
        if len(events) == 1:
            return {"tool": "calendar_delete_event", "args": {"event_id": events[0]["id"]}}

        # Si hay varias, intentamos desempatar por palabras clave descriptivas
        matching_events = []
        for ev in events:
            title_lower = ev.get("title", "").lower()
            desc_lower = ev.get("description", "").lower()
            loc_lower = ev.get("location", "").lower()

            words = [w for w in msg_clean.split() if len(w) > 3 and w not in [
                "elimina", "eliminar", "borra", "borrar", "cancela", "cancelar", "cita", "reunión", "evento", "compromiso", "julio"
            ]]
            for w in words:
                if w in title_lower or w in desc_lower or w in loc_lower:
                    matching_events.append(ev)
                    break

        if len(matching_events) == 1:
            return {"tool": "calendar_delete_event", "args": {"event_id": matching_events[0]["id"]}}

        return None
    except Exception:
        return None


def parse_calendar_update_directly(msg: str) -> dict | None:
    from datetime import datetime
    from app.adapters.calendar_db import list_events

    msg_clean = msg.lower().strip()
    if not re.search(r"\b(cambia|cambiar|modifica|modificar|actualiza|actualizar|apunta|mueve|mover)\b", msg_clean):
        return None
    if not re.search(r"\b(cita|reunión|evento|compromiso|hora|fecha)\b", msg_clean):
        return None

    def text_number_to_digit(text: str) -> str:
        words_map = {
            "una": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6",
            "siete": "7", "ocho": "8", "nueve": "9", "diez": "10", "once": "11", "doce": "12",
            "trece": "13", "catorce": "14", "quince": "15", "dieciséis": "16", "diecisiete": "17",
            "dieciocho": "18", "diecinueve": "19", "veinte": "20", "veintiuno": "21", "veintidós": "22",
            "veintitrés": "23", "veinticuatro": "24"
        }
        for word, digit in words_map.items():
            text = re.sub(r"\b" + word + r"\b", digit, text, flags=re.IGNORECASE)
        return text

    msg_clean = text_number_to_digit(msg_clean)

    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    date_matched = False

    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    date_match = re.search(r"\b(?:el|del|de)\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_clean)
    if date_match:
        day = int(date_match.group(1))
        month = months_map[date_match.group(2)]
        date_matched = True
    else:
        date_match = re.search(r"\b(?:el|del|de)\s+(?:d[ií]a\s+)?(\d{1,2})\b", msg_clean)
        if date_match:
            day = int(date_match.group(1))
            date_matched = True

    if not date_matched:
        return None

    date_str = f"{year}-{month:02d}-{day:02d}"

    time_match = re.search(r"\b(?:para|a)\s+las?\s*(\d{1,2})[:.](\d{2})\b", msg_clean)
    new_hour = None
    new_minute = 0
    if time_match:
        new_hour = int(time_match.group(1))
        new_minute = int(time_match.group(2))
    else:
        time_match_short = re.search(r"\b(?:para|a)\s+las?\s*(\d{1,2})\b", msg_clean)
        if time_match_short:
            new_hour = int(time_match_short.group(1))

    if new_hour is None:
        return None

    if new_hour <= 7:
        new_hour += 12

    new_start_time = f"{date_str} {new_hour:02d}:{new_minute:02d}"

    try:
        events = list_events(start_date=date_str, end_date=date_str)
        if not events:
            return None

        event_id = None
        if len(events) == 1:
            event_id = events[0]["id"]
        else:
            words = [w for w in msg_clean.split() if len(w) > 3 and w not in [
                "cambia", "cambiar", "modifica", "modificar", "actualiza", "actualizar", "cita", "reunión", "hora", "fecha", "julio", "para"
            ]]
            for ev in events:
                title_lower = ev.get("title", "").lower()
                desc_lower = ev.get("description", "").lower()
                loc_lower = ev.get("location", "").lower()
                for w in words:
                    if w in title_lower or w in desc_lower or w in loc_lower:
                        event_id = ev["id"]
                        break
                if event_id:
                    break

        if event_id:
            return {
                "tool": "calendar_update_event",
                "args": {
                    "event_id": event_id,
                    "start_time": new_start_time
                }
            }
        return None
    except Exception:
        return None


def parse_calendar_create_directly(msg: str, history: list = None) -> dict | None:
    from datetime import datetime, timedelta
    
    # Auxiliar para convertir números escritos en palabras a dígitos
    def text_number_to_digit(text: str) -> str:
        words_map = {
            "una": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6",
            "siete": "7", "ocho": "8", "nueve": "9", "diez": "10", "once": "11", "doce": "12",
            "trece": "13", "catorce": "14", "quince": "15", "dieciséis": "16", "diecisiete": "17",
            "dieciocho": "18", "diecinueve": "19", "veinte": "20", "veintiuno": "21", "veintidós": "22",
            "veintitrés": "23", "veinticuatro": "24"
        }
        for word, digit in words_map.items():
            text = re.sub(r"\b" + word + r"\b", digit, text, flags=re.IGNORECASE)
        return text

    msg_lower = text_number_to_digit(msg.lower().strip())
    
    # 1. Comprobar verbos (incluidos: anota, anotar, registra, registrar)
    if not re.search(r"\b(apunta|apuntar|punta|puntar|agenda|agendar|programa|programar|crea|cre|crear|añade|añadir|anota|anotar|registra|registrar)\b", msg_lower):
        # --- CASO DE RESPUESTA A LA PREGUNTA DE HORA/LUGAR ---
        if history:
            last_assistant_msg = None
            for h in reversed(history):
                if h.get("role") == "assistant":
                    last_assistant_msg = h.get("content", "").lower()
                    break
            if last_assistant_msg and "¿para qué hora" in last_assistant_msg:
                time_match = re.search(r"\ba las?\s*(\d{1,2})[:.](\d{2})\b", msg_lower)
                hour = None
                minute = 0
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                else:
                    time_match_short = re.search(r"\ba las?\s*(\d{1,2})\b", msg_lower)
                    if time_match_short:
                        hour = int(time_match_short.group(1))
                    else:
                        time_match_hours = re.search(r"\ba las?\s*(\d{1,2})\s*horas\b", msg_lower)
                        if time_match_hours:
                            hour = int(time_match_hours.group(1))
                            
                # Fallback: buscar cualquier número si solo dice la hora a secas (ej: "las 3", "3")
                if hour is None:
                    match_any_num = re.search(r"\b(\d{1,2})\b", msg_lower)
                    if match_any_num:
                        hour = int(match_any_num.group(1))
                
                if hour is not None:
                    # Asumir PM si la hora es de 1 a 7 (ej: las 3 -> las 15)
                    if hour <= 7:
                        hour += 12
                        
                    months_map = {
                        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
                        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
                    }
                    date_match = re.search(r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", last_assistant_msg)
                    if date_match:
                        day = int(date_match.group(1))
                        month = months_map[date_match.group(2)]
                        year = datetime.now().year
                        
                        title = "Cita agendada"
                        title_match = re.search(r"\b(cita|reunión|evento|compromiso)\s+(?:del?\s+\d+\s+de\s+[a-z]+\s+)?(?:en|con|para|de)\s+([^?]+)", last_assistant_msg)
                        if title_match:
                            title = f"{title_match.group(1).capitalize()} {title_match.group(2).strip()}"
                            
                        start_time_str = f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
                        return {
                            "tool": "calendar_create_event",
                            "args": {
                                "title": title,
                                "start_time": start_time_str,
                                "description": f"Agendado automáticamente: {msg} (siguiendo contexto: {last_assistant_msg})"
                            }
                        }
        return None

    if not re.search(r"\b(cita|reunión|evento|compromiso)\b", msg_lower):
        return None
        
    # 2. Extraer la fecha
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    date_matched = False
    
    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }
    months_names = {v: k for k, v in months_map.items()}
    
    # Intentar formato ISO YYYY-MM-DD primero
    iso_date_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", msg_lower)
    if iso_date_match:
        year = int(iso_date_match.group(1))
        month = int(iso_date_match.group(2))
        day = int(iso_date_match.group(3))
        date_matched = True
    else:
        date_match = re.search(r"\bel\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_lower)
        if date_match:
            day = int(date_match.group(1))
            month = months_map[date_match.group(2)]
            date_matched = True
        else:
            date_match = re.search(r"\b(?:el|del|de)\s+(?:d[ií]a\s+)?(\d{1,2})\b", msg_lower)
            if date_match:
                day = int(date_match.group(1))
                date_matched = True
            elif "mañana" in msg_lower:
                tomorrow = now + timedelta(days=1)
                year = tomorrow.year
                month = tomorrow.month
                day = tomorrow.day
                date_matched = True
            elif "hoy" in msg_lower:
                date_matched = True
                
    if not date_matched:
        return None
        
    # 3. Extraer la hora
    time_match = re.search(r"\ba las?\s*(\d{1,2})[:.](\d{2})\b", msg_lower)
    hour = None
    minute = 0
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
    else:
        time_match_short = re.search(r"\ba las?\s*(\d{1,2})\b", msg_lower)
        if time_match_short:
            hour = int(time_match_short.group(1))
        else:
            time_match_hours = re.search(r"\ba las?\s*(\d{1,2})\s*horas\b", msg_lower)
            if time_match_hours:
                hour = int(time_match_hours.group(1))

    # Extraer título
    title = "Cita agendada"
    title_match = re.search(r"\b(cita|reunión|evento|compromiso)\s+(?:en|con|para|de)\s+([^,.]+)", msg, re.IGNORECASE)
    if title_match:
        title = f"{title_match.group(1).capitalize()} {title_match.group(2).strip()}"
    else:
        clean_title = re.sub(r"^(apunta|apuntar|punta|puntar|agenda|agendar|programa|programar|crea|crear|añade|añadir|anota|anotar|registra|registrar)\s+", "", msg, flags=re.IGNORECASE)
        if len(clean_title) > 5:
            title = clean_title.strip()

    # Sanitizar el título para remover la referencia a la fecha (evitar duplicados en la respuesta)
    title_clean = re.sub(r"\b(?:para el|del|el)?\s*(?:d[ií]a\s+)?\d+\b", "", title, flags=re.IGNORECASE).strip()
    title_clean = re.sub(r"\bde\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", "", title_clean, flags=re.IGNORECASE).strip()
    title_clean = re.sub(r"^(en|con|para|de)\s+", "", title_clean, flags=re.IGNORECASE).strip()

    month_name = months_names[month]

    # SI NO SE DETECTA LA HORA: Preguntar interactivamente por ella (Bypass conversacional)
    if hour is None:
        title_suffix = f"en {title_clean}" if title_clean else ""
        return {
            "type": "chat",
            "response": f"Entendido. ¿Para qué hora quieres agendar la cita del {day} de {month_name} {title_suffix}?".strip().replace("  ", " ")
        }
        
    start_time_str = f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
    return {
        "tool": "calendar_create_event",
        "args": {
            "title": title,
            "start_time": start_time_str,
            "description": f"Agendado automáticamente: {msg}"
        }
    }


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

    # 5. CREATE DIRECTORY (crea una carpeta en la ruta C:/... / crea una carpeta llamada X en el escritorio)
    m_path = re.search(r"\b(?:crea|crear)\s+(?:una\s+carpeta\s+|un\s+directorio\s+)(?:en\s+la\s+ruta\s+|en\s+)?(\S+)", msg_clean, re.IGNORECASE)
    if m_path:
        path_candidate = m_path.group(1)
        if is_likely_path(path_candidate):
            return {"tool": "create_directory", "args": {"path": resolve_path(path_candidate)}}

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
    m = re.search(r"\b(?:crea|escribir|escribe)\s+(?:un\s+archivo\s+|el\s+archivo\s+)?(?:en\s+la\s+ruta\s+|en\s+)?(\S+)\s+(?:que\s+diga|con\s+contenido)\s+(.+)", msg_clean, re.IGNORECASE)
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
                
        if is_likely_path(filename):
            final_path = resolve_path(filename)
        else:
            final_path = f"{folder}/{filename}" if folder else resolve_path(filename)
        return {"tool": "create_file", "args": {"path": final_path, "content": content}}

    # 9. MOVE FILE (mueve X a Y)
    m = re.search(r"\b(?:mueve|mover|mueva|desplaza|desplazar)\s+(?:el\s+archivo\s+|la\s+carpeta\s+)?(\S+)\s+(?:a|hacia)\s+(\S+)", msg_clean, re.IGNORECASE)
    if m:
        src = m.group(1)
        dst = m.group(2)
        if is_likely_path(src) and is_likely_path(dst):
            return {"tool": "move_file", "args": {
                "old_path": resolve_path(src),
                "new_path": resolve_path(dst),
                "src": resolve_path(src),
                "dst": resolve_path(dst)
            }}

    return None
class PlannerOrchestrator:
    """
    Pipeline único de Alfonso (post Fase 2): no hay EventBus ni AgentRegistry.
    Todo pasa por aquí — detección de intent, llamada al LLM, ejecución de
    tool (cliente vía bridge o servidor vía tool_registry) y, si aplica,
    persistencia en la memoria corta de Fase 1 (SessionMemory).
    """

    async def run(self, user_message, llm, request_id=None, session_id=None, client_id=None):
        from app.adapters.alfonso_bridge import bridge
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run() — request_id=%s, session_id=%s, client_id=%s", request_id, session_id, client_id)
        user_message = _normalize_message(user_message)

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
        _check_and_store_fact(user_message, session_id, client_id=client_id)

        # Persistimos el turno del usuario en memoria corta ANTES de generar,
        # sea cual sea el intent. Así un mensaje "tool" también queda en el
        # historial que un futuro turno "chat" podrá recuperar como contexto.
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
        # DETECCION DE TOOL DIRECTA (DETERMINISTA / BYPASS)
        # ------------------------------------------------------------
        history_msgs = memory.get_history(session_id, client_id=client_id) if session_id else []
        
        # 0. Composite open calendar and mail bypass rule
        direct_tool = parse_composite_operations(user_message)
                
        if not direct_tool:
            direct_tool = parse_file_operation_directly(user_message, bridge.client_info, history_msgs)
        if not direct_tool:
            direct_tool = parse_calendar_operation_directly(user_message)
        if not direct_tool:
            direct_tool = parse_calendar_create_directly(user_message, history_msgs)
        if not direct_tool:
            direct_tool = parse_calendar_update_directly(user_message)
        if not direct_tool:
            direct_tool = parse_calendar_delete_directly(user_message)
        if not direct_tool:
            direct_tool = parse_mail_operation_directly(user_message)
        if not direct_tool:
            direct_tool = parse_system_operation_directly(user_message)
        if not direct_tool:
            direct_tool = parse_memory_operation_directly(user_message)
        if not direct_tool:
            direct_tool = parse_browser_operation_directly(user_message)
        
        is_bypass_tool = False
        if direct_tool:
            if not isinstance(direct_tool, list) and direct_tool.get("type") == "chat":
                response = direct_tool["response"]
                logger.info("Filtro determinista: respuesta de chat directa: %s", response)
                if session_id:
                    memory.add_message(session_id, "assistant", response, client_id=client_id)
                return {
                    "type": "chat",
                    "response": response,
                }
            is_bypass_tool = True

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
            
            # Copiar archivos del sandbox al escritorio si se pide explícitamente
            if "escritorio" in msg_lower or "desktop" in msg_lower:
                try:
                    import os
                    from pathlib import Path
                    from app.tools.server.filesystem_tools import _resolve_path
                    sandbox_path = Path("data/dev_sandbox")
                    if sandbox_path.exists():
                        # Detectar si hay solicitud de subcarpeta (ej: "dentro de una carpeta que se llame proyecto_alfonso_marketing")
                        subfolder = None
                        m_sub = re.search(r"\b(?:carpeta\s+que\s+se\s+llame|carpeta\s+llamada|subcarpeta\s+llamada|directorio\s+llamado|carpeta)\s+([a-zA-Z0-9_\-]+)", msg_lower)
                        if m_sub:
                            subfolder = m_sub.group(1).strip()
                            
                        for entry in os.scandir(sandbox_path):
                            if entry.is_file():
                                file_content = Path(entry.path).read_text(encoding="utf-8")
                                if subfolder:
                                    dest_path = f"C:/Users/luisd/Desktop/{subfolder}/{entry.name}"
                                else:
                                    dest_path = f"C:/Users/luisd/Desktop/{entry.name}"
                                resolved_dest = _resolve_path(dest_path)
                                # Asegurar que la subcarpeta destino exista
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

        router = _router.detect_with_detail(user_message)

        # ------------------------------------------------------------
        # CHAT
        # ------------------------------------------------------------
        if not is_bypass_tool and router["intent"] == "chat" and not _force_tool(user_message):
            logger.info("Intent detectado: chat (no se fuerza tool)")

            response = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
                client_id=client_id,
            )

            if session_id:
                memory.add_message(session_id, "assistant", response, client_id=client_id)

            return {
                "type": "chat",
                "response": response,
            }

        # ------------------------------------------------------------
        # EJECUCION DE BYPASS DETERMINISTA DETECTADO
        # ------------------------------------------------------------
        if is_bypass_tool and isinstance(direct_tool, list):
            multi_results = []
            for t_info in direct_tool:
                t_name = t_info["tool"]
                t_args = t_info["args"]
                logger.info("Filtro determinista: ejecutando parte de multi-tool %s con args %s", t_name, t_args)
                
                if is_client_tool(t_name):
                    action = get_client_action(t_name)
                    res = await bridge.send_command(action, t_args)
                    exec_mode = "client"
                else:
                    tool_func = get_tool(t_name, request_id)
                    if tool_func:
                        res = await tool_func(**t_args)
                        exec_mode = "server"
                    else:
                        res = {"status": "error", "error": f"Tool {t_name} no encontrada"}
                        exec_mode = "server"
                
                multi_results.append({
                    "tool": t_name,
                    "execution": exec_mode,
                    "args": t_args,
                    "result": res
                })
            return {
                "type": "multi_tool",
                "results": multi_results
            }

        tool_name = None
        args = {}
        result = None
        execution = "server"

        if is_bypass_tool and direct_tool:
            tool_name = direct_tool["tool"]
            args = direct_tool["args"]
            logger.info("Filtro determinista: detectada tool %s con args %s", tool_name, args)
            
            # Ejecutar bypass tool determinista de un solo disparo
            if is_client_tool(tool_name):
                logger.info("Ejecutando tool de cliente (bypass): %s", tool_name)
                action = get_client_action(tool_name)
                result = await bridge.send_command(action, args, client_id=client_id)
                execution = "client"
            else:
                logger.info("Ejecutando tool de servidor (bypass): %s", tool_name)
                tool = get_tool(tool_name, request_id)
                if not tool:
                    return {
                        "type": "error",
                        "message": f"No existe {tool_name}",
                    }
                # Validar/Adaptar argumentos
                validation_res = prepare_tool_args(tool_name, args, request_id)
                if not validation_res.ok:
                    return {
                        "type": "error",
                        "message": validation_res.error,
                    }
                args = validation_res.args
                # Inyectar session_id y client_id
                try:
                    sig = inspect.signature(tool)
                    if "session_id" in sig.parameters:
                        args["session_id"] = session_id or "global"
                    if "client_id" in sig.parameters:
                        args["client_id"] = client_id
                except Exception:
                    pass
                
                if asyncio.iscoroutinefunction(tool):
                    result = await asyncio.wait_for(tool(**args), timeout=_TOOL_TIMEOUT)
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(loop.run_in_executor(None, lambda: tool(**args)), timeout=_TOOL_TIMEOUT)
                execution = "server"
        else:
            # ------------------------------------------------------------
            # TOOL — parseo de la respuesta del LLM en modo tool y ejecución con bucle de autocorrección
            # ------------------------------------------------------------
            max_attempts = 3
            current_attempt = 0
            
            while current_attempt < max_attempts:
                current_attempt += 1
                logger.info("Ciclo de ejecución de tool: Intento %d de %d", current_attempt, max_attempts)

                # Reconstruir memory_text con el historial de mensajes actualizado (que incluye los fallos previos)
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
                logger.info("LLM tool response (Intento %d): %s", current_attempt, data)
                if not data:
                    error.warning("LLM no devolvió JSON de tool válido (Intento %d)", current_attempt)
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "message": "JSON tool inválido",
                            "raw": raw,
                        }
                    if session_id:
                        memory.add_message(session_id, "system", f"Error: Tu respuesta anterior no contenía un JSON de herramienta válido. Por favor, genera únicamente el JSON de la herramienta.", client_id=client_id)
                    continue

                tool_name, args = _extract_tool_and_args(data)

                if not tool_name:
                    if current_attempt == max_attempts:
                        return {
                            "type": "error",
                            "message": "Tool desconocida o no especificada",
                        }
                    if session_id:
                        memory.add_message(session_id, "system", f"Error: No se pudo identificar el nombre de la herramienta a partir de tu JSON: {data}.", client_id=client_id)
                    continue

                # ------------------------------------------------------------
                # EJECUCIÓN — cliente (bridge) o servidor (tool_registry)
                # ------------------------------------------------------------
                if is_client_tool(tool_name):
                    logger.info("Ejecutando tool de cliente: %s", tool_name)
                    action = get_client_action(tool_name)
                    logger.info("Enviando al cliente %s", action)

                    result = await bridge.send_command(action, args, client_id=client_id)

                    if not isinstance(result, dict) or result.get("status") == "error":
                        error.warning(
                            "Tool de cliente falló (Intento %d): %s -> %s",
                            current_attempt,
                            tool_name,
                            result,
                        )
                        if current_attempt == max_attempts:
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
                        if session_id:
                            import json
                            memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
                            memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}. Corrige los parámetros y vuelve a intentar.", client_id=client_id)
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
                        continue

                    # Validar/Adaptar argumentos usando el esquema de la Fase 1
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
                        continue
                    args = validation_res.args

                    # Inyectar session_id y client_id si la firma de la función lo requiere
                    try:
                        sig = inspect.signature(tool)
                        if "session_id" in sig.parameters:
                            args["session_id"] = session_id or "global"
                        if "client_id" in sig.parameters:
                            args["client_id"] = client_id
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
                        if current_attempt == max_attempts:
                            return {
                                "type": "error",
                                "execution": "server",
                                "tool": tool_name,
                                "message": str(e),
                            }
                        if session_id:
                            memory.add_message(session_id, "system", f"Error: La ejecución de la herramienta '{tool_name}' falló con una excepción: {str(e)}", client_id=client_id)
                        continue

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
                                    "message": f"El archivo se guardó pero tiene errores de sintaxis que debes corregir de inmediato: {error_msg}"
                                }
                            except Exception as e:
                                logger.warning("No se pudo validar la sintaxis del archivo: %s", e)

                    if isinstance(result, dict) and result.get("status") == "error":
                        error.warning(
                            "Tool de servidor falló (Intento %d): %s -> %s",
                            current_attempt,
                            tool_name,
                            result,
                        )
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
                            memory.add_message(session_id, "system", f"Tool output: {json.dumps(result)}. Por favor, corrige los errores e inténtalo de nuevo.", client_id=client_id)
                        continue

                    execution = "server"
                
                # Ejecución exitosa de tool, salimos del ciclo
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
            "result": result,
        }