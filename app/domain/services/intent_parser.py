import re
import os
import json
import unicodedata
from datetime import datetime, timedelta

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

FORCE_TOOL_KEYWORDS = [
    "abre", "open", "lanza", "ejecuta", "click", "escribe", "escriba", "escribir", "escribas",
    "añade", "añada", "añde", "anade", "añadi", "añadir", "anadir", "añadas", "anada",
    "agrega", "agregar", "agregue", "ponga", "poner", "navega", "visita", "crea", "crear",
    "borra", "borrar", "borar", "elimina", "elmina", "elminar", "suprime", "suprimir",
    "cierra", "cerrar", "renombra", "renombrar", "cambia", "cambiar", "cambiae", "cambiá",
]

COMPOSITE_SPLIT_RE = re.compile(r'\by\b|\bpero\b|,')

CAL_OPEN_RE = re.compile(r"\b(abre|abrir|mostrar|ver)\b.{0,20}\b(el calendario|calendario|citas|agenda)\b")
CAL_TODAY_RE = re.compile(r"\b(qu[eé] tengo hoy|citas de hoy|agenda de hoy)\b")
CAL_LIST_RE = re.compile(r"\b(?:lista|listá|listar|mostrar|muestra|dime|ver|veo)\b.*\b(?:citas|eventos|reuniones|compromisos|calendario|agenda)\b")
CAL_CLOSE_RE = re.compile(r"\b(cierra|cerrar|oculta|ocultar)\b.{0,20}\b(el calendario|calendario|citas|agenda)\b")

def normalize_message(msg: str) -> str:
    return _TRAILING_PUNCT_RE.sub("", msg.strip())

def force_tool(msg: str) -> bool:
    msg = msg.lower()
    return any(x in msg for x in FORCE_TOOL_KEYWORDS)

def find_base_path_in_history(folder_name: str, history: list) -> str | None:
    pattern = re.compile(rf"((?:[a-zA-Z]:|/mnt/[a-z]/Users/[^/]+|/home/[^/]+)/[^ ]+/{re.escape(folder_name)})", re.IGNORECASE)
    for msg in history:
        content = msg.get("content", "")
        m = pattern.search(content.replace("\\", "/"))
        if m:
            return m.group(1)
    return None

def parse_composite_operations(msg: str) -> list | None:
    msg_clean = msg.lower().strip()
    
    open_words = ["abrir", "abre", "muestra", "mostrar", "ver", "pantalla"]
    close_words = ["cerrar", "cierra", "oculta", "ocultar"]
    
    parts = COMPOSITE_SPLIT_RE.split(msg_clean)
    tools = []
    
    for part in parts:
        part = part.strip()
        is_open = any(w in part for w in open_words)
        is_close = any(w in part for w in close_words)
        
        has_cal = any(x in part for x in ["calendario", "agenda", "citas"])
        has_mail = any(y in part for y in ["correo", "mail", "email", "recibidos"])
        
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
    msg_clean = msg.lower().strip()
    if CAL_OPEN_RE.search(msg_clean):
        return {"tool": "calendar_open_ui", "args": {}}
    if CAL_TODAY_RE.search(msg_clean):
        if not any(x in msg_clean for x in ["correo", "mail", "email"]):
            today_str = datetime.now().strftime("%Y-%m-%d")
            return {"tool": "calendar_list_events", "args": {"start_date": today_str, "end_date": today_str}}
    if CAL_LIST_RE.search(msg_clean):
        return {"tool": "calendar_list_events", "args": {}}
    if CAL_CLOSE_RE.search(msg_clean):
        return {"tool": "calendar_close_ui", "args": {}}
    return None

def parse_mail_operation_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    if re.search(r"\b(genera(r)?|crea(r)?|inyecta(r)?|pon(er)?) (correos|mails|emails) (de prueba|simulados)\b", msg_clean):
        return {"tool": "mail_receive_mock_emails", "args": {}}
    if re.search(r"\b(resumen de(l)? (correo|mail)|resume(ir)? los correos|resumen de la mañana|notificaciones de correo|resumen matutino)\b", msg_clean):
        return {"tool": "mail_get_unread_summary", "args": {}}
    if re.search(r"\b(clasifica(r)? (el |los )?(correo|mail|correos|emails))\b", msg_clean):
        return {"tool": "mail_classify_emails", "args": {}}
    if re.search(r"\b(abrir|abre|muestra|mostrar|ver|pantalla) (el |la |los |las )?(cliente de correo|bandeja de entrada|correo visual|ventana de correo|recibidos|correo|correos|mail|mails|email|emails)\b", msg_clean) or msg_clean in ("abre correo", "abrir correo"):
        return {"tool": "mail_open_ui", "args": {}}
    if re.search(r"\b(cierra|cerrar|oculta|ocultar) (el |la |los |las )?(cliente de correo|bandeja de entrada|correo visual|ventana de correo|recibidos|correo|correos|mail|mails|email|emails)\b", msg_clean):
        return {"tool": "mail_close_ui", "args": {}}
    if re.search(r"\b(?:lee|leer|lista|listá|listar|dame|ver|mostrar|muestra)\b.*\b(?:correo|mail|correos|emails|mails)\b", msg_clean):
        return {"tool": "mail_list_emails", "args": {}}
    return None

def parse_system_operation_directly(msg: str, session_id: str | None = None) -> dict | None:
    msg_clean = msg.lower().strip()
    if re.search(r"\b(qu[eé]\s+hora\s+es|dime\s+la\s+hora|qu[eé]\s+hora\s+tienes|fecha\s+de\s+hoy|qu[eé]\s+d[ií]a\s+es\s+hoy|fecha\s+y\s+hora)\b", msg_clean):
        return {"tool": "get_current_datetime", "args": {}}
    if re.search(r"\b(captura\s+de\s+pantalla|toma\s+una\s+captura|pantallazo|hacer\s+captura|hace\s+captura)\b", msg_clean):
        return {"tool": "screenshot", "args": {}}
    if re.search(r"\b(ventanas\s+abiertas|lista\s+las\s+ventanas|mostrar\s+ventanas|ver\s+ventanas)\b", msg_clean):
        return {"tool": "window_list", "args": {}}
    
    if re.search(r"\b(proyectos\s+tenemos\s+abiertos|lista\s+de\s+proyectos|proyectos\s+activos|proyectos\s+guardados)\b", msg_clean):
        from app.adapters.memory import memory
        conversations = memory.list_persistent_conversations()
        if not conversations:
            response_text = "Actualmente no tienes ningún proyecto registrado o abierto."
        else:
            projects_grouped = {}
            for c in conversations:
                p_name = c.get("project_name") or "Otros / General"
                if p_name not in projects_grouped:
                    projects_grouped[p_name] = []
                projects_grouped[p_name].append(c)

            lines = [f"Actualmente tienes **{len(projects_grouped)} proyectos** abiertos en el sistema:"]
            for p_name, convs in sorted(projects_grouped.items()):
                lines.append(f"\n📁 **{p_name.upper()}**:")
                for c in convs:
                    lines.append(f"  - *{c['title']}* (Disciplina: {c['discipline']})")
            response_text = "\n".join(lines)
        return {
            "type": "chat",
            "response": response_text
        }

    if re.search(r"\b(conversaciones|canales|hilos|chats)\b.*\b(este proyecto|proyecto activo|proyecto cargado)\b", msg_clean):
        from app.adapters.memory import memory
        curr_session_id = session_id or "default"
        meta = memory.get_metadata(curr_session_id)
        if not meta or meta.get("project_name") == "default":
            response_text = "Actualmente no tienes cargado ningún proyecto de trabajo en el asistente. Por favor, selecciona un proyecto para ver sus conversaciones."
        else:
            proj_name = meta["project_name"]
            all_convs = memory.list_persistent_conversations()
            project_convs = [c for c in all_convs if c.get("project_name") == proj_name]
            if not project_convs:
                response_text = f"En el proyecto *{proj_name}*, no se han realizado conversaciones aún."
            else:
                lines = [f"Las conversaciones involucradas en el proyecto *{proj_name}* son:"]
                for c in project_convs:
                    lines.append(f"- **{c['title']}** (Disciplina: {c['discipline']})")
                response_text = "\n".join(lines)
        return {
            "type": "chat",
            "response": response_text
        }

    m_open = re.search(r"\b(?:abre|abrir|carga|cargar|selecciona|seleccionar|cambia\s+al|cambiar\s+al)\b.*\bproyecto\s+(?:de|del)?\s*(.+)", msg_clean, re.IGNORECASE)
    if m_open:
        project_query = m_open.group(1).strip()
        project_query = re.sub(r'^(?:el|la|los|las|de|del|d|l)\\s+', '', project_query, flags=re.IGNORECASE)
        if project_query.lower().startswith('l '):
            project_query = project_query[2:]
            
        from app.adapters.memory import memory
        projects = memory.list_persistent_conversations()
        
        def clean_accents(s: str) -> str:
            nfkd = unicodedata.normalize('NFKD', s)
            return ''.join([c for c in nfkd if not unicodedata.combining(c)]).lower()

        best_match = None
        for p in projects:
            title_clean = clean_accents(p["title"])
            name_clean = clean_accents(p["project_name"])
            query_clean = clean_accents(project_query)
            if query_clean in title_clean or query_clean in name_clean:
                best_match = p
                break
                
        if best_match:
            return {
                "type": "tool",
                "tool": "switch_project_session",
                "args": {
                    "session_id": best_match["session_id"],
                    "title": best_match["title"],
                    "discipline": best_match["discipline"],
                    "project_name": best_match["project_name"]
                }
            }
        else:
            return {
                "type": "chat",
                "response": f"Lo siento, no he podido encontrar ningún proyecto que coincida con '{project_query}'."
            }
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
    m = re.search(r"\b(?:abre|abrir|navega|navegar|entra|entrar|ir\s+a)\b.*\b([a-zA-Z0-9.\-_/:]+\.[a-zA-Z]{2,6}(?:/[^\s]*)?)", msg_clean, re.IGNORECASE)
    if m:
        url = m.group(1).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return {"tool": "open_url", "args": {"url": url}}
    return None

def parse_calendar_delete_directly(msg: str) -> dict | None:
    msg_clean = msg.lower().strip()
    if not re.search(r"\b(elimina|eliminar|borra|borrar|cancela|cancelar|quita|quitar)\b", msg_clean):
        return None
    if not re.search(r"\b(cita|reunión|reunion|evento|compromiso|citas|reuniones|eventos|compromisos)\b", msg_clean):
        return None

    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    if "todo" in msg_clean or "todas" in msg_clean:
        month_match = re.search(r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_clean)
        if month_match:
            from app.adapters.calendar_db import list_events, delete_event
            from app.adapters.alfonso_bridge import bridge
            import asyncio
            
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

    if not re.search(r"\b(el|del|de|día|dia)\s+\d+", msg_clean):
        match = re.search(r"\b(?:id|número|núm|nº|evento|cita)\s*(\d+)\b", msg_clean)
        if match:
            event_id = int(match.group(1))
            return {"tool": "calendar_delete_event", "args": {"event_id": event_id}}

    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    date_matched = False

    date_match = re.search(r"\b(?:el|del)\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", msg_clean)
    if date_match:
        day = int(date_match.group(1))
        month = months_map[date_match.group(2)]
        date_matched = True
    else:
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
        from app.adapters.calendar_db import list_events
        events = list_events(start_date=date_str, end_date=date_str)
        if not events:
            return None

        if len(events) == 1:
            return {"tool": "calendar_delete_event", "args": {"event_id": events[0]["id"]}}

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
    
    if not re.search(r"\b(apunta|apuntar|punta|puntar|agenda|agendar|programa|programar|crea|cre|crear|añade|añadir|anota|anotar|registra|registrar)\b", msg_lower):
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
                            
                if hour is None:
                    match_any_num = re.search(r"\b(\d{1,2})\b", msg_lower)
                    if match_any_num:
                        hour = int(match_any_num.group(1))
                
                if hour is not None:
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
                        title_match = re.search(r"\b(cita|reunión|evento|compromiso)\s+(?:del?\\s+\d+\s+de\s+[a-z]+\s+)?(?:en|con|para|de)\s+([^?]+)", last_assistant_msg)
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
        
    year = datetime.now().year
    month = datetime.now().month
    day = datetime.now().day
    date_matched = False
    
    months_map = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }
    months_names = {v: k for k, v in months_map.items()}
    
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
                tomorrow = datetime.now() + timedelta(days=1)
                year = tomorrow.year
                month = tomorrow.month
                day = tomorrow.day
                date_matched = True
            elif "hoy" in msg_lower:
                date_matched = True
                
    if not date_matched:
        return None
        
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

    title = "Cita agendada"
    title_match = re.search(r"\b(cita|reunión|evento|compromiso)\s+(?:en|con|para|de)\s+([^,.]+)", msg, re.IGNORECASE)
    if title_match:
        title = f"{title_match.group(1).capitalize()} {title_match.group(2).strip()}"
    else:
        clean_title = re.sub(r"^(apunta|apuntar|punta|puntar|agenda|agendar|programa|programar|crea|crear|añade|añadir|anota|anotar|registra|registrar)\s+", "", msg, flags=re.IGNORECASE)
        if len(clean_title) > 5:
            title = clean_title.strip()

    title_clean = re.sub(r"\b(?:para el|del|el)?\s*(?:d[ií]a\s+)?\d+\b", "", title, flags=re.IGNORECASE).strip()
    title_clean = re.sub(r"\bde\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", "", title_clean, flags=re.IGNORECASE).strip()
    title_clean = re.sub(r"^(en|con|para|de)\s+", "", title_clean, flags=re.IGNORECASE).strip()

    month_name = months_names[month]

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
            
        if "/" not in p and "\\" not in p:
            last_folder = None
            for h in reversed(history):
                try:
                    h_data = json.loads(h.get("content", ""))
                    tool_args = h_data.get("args", {})
                    path_val = tool_args.get("path", "")
                    if path_val:
                        path_val = path_val.replace("\\", "/")
                        if h_data.get("tool") in ("create_directory",):
                            last_folder = path_val
                            break
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

    m = re.search(r"\b(?:renombra|renombrá|cambia|cambiar|cambiae)\s+(?:el\s+nombre\s+de\s+|el\s+archivo\s+|la\s+carpeta\s+)?(\S+)\s+(?:a|por)\s+(\S+)", msg_clean, re.IGNORECASE)
    if not m:
        m = re.search(r"\b(?:el\s+archivo\s+)?(?:dentro\s+de\s+\S+\s+)?(?:que\s+se\s+llama\s+)?(\S+)\s+(?:cambia|cambiae|renombra|cambiá)\s+(?:el\s+nombre\s+)?(?:a|por)\s+(\S+)", msg_clean, re.IGNORECASE)
        
    if m:
        src = m.group(1)
        if is_likely_path(src):
            src_res = resolve_path(src)
            dst_raw = m.group(2).strip().replace("\\", "/")
            new_name = dst_raw.split("/")[-1]
            return {"tool": "rename_file", "args": {"path": src_res, "new_name": new_name}}

    m = re.search(r"\b(?:lee|leé)\s+(?:el\s+archivo\s+|contenido\s+de\s+)?(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "read_file", "args": {"path": resolve_path(path)}}

    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar|suprime)\s+el\s+archivo\s+(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "delete_file", "args": {"path": resolve_path(path)}}

    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar)\s+la\s+carpeta\s+(\S+)", msg_clean, re.IGNORECASE)
    if m:
        path = m.group(1)
        if is_likely_path(path):
            return {"tool": "delete_directory", "args": {"path": resolve_path(path)}}

    m_path = re.search(r"\b(?:crea|crear)\s+(?:una\s+carpeta\s+|un\s+directorio\s+)(?:en\s+la\s+ruta\s+|en\s+)?(\S+)", msg_clean, re.IGNORECASE)
    if m_path:
        path_candidate = m_path.group(1)
        if is_likely_path(path_candidate):
            return {"tool": "create_directory", "args": {"path": resolve_path(path_candidate)}}

    m = re.search(r"\bcrea\s+(?:una\s+carpeta\s+|un\s+directorio\s+)(?:de\s+mi\s+|en\s+mi\s+|en\s+el\s+)?(?:escritorio|desktop)?\s*(?:que\s+se\s+llame\s+|llamada\s+|llamado\s+)?([a-zA-Z0-9_\-\s]+)", msg_clean, re.IGNORECASE)
    if m:
        folder_name = m.group(1).strip()
        folder_name = re.sub(r"\s+(?:en\s+mi\s+|en\s+el\s+|de\s+mi\s+)?(?:escritorio|desktop)$", "", folder_name, flags=re.IGNORECASE).strip()
        if "escritorio" in msg_clean.lower() or "desktop" in msg_clean.lower():
            res_path = f"{desktop}/{folder_name}"
        else:
            res_path = f"{home}/{folder_name}"
        return {"tool": "create_directory", "args": {"path": res_path}}

    m = re.search(r"\b(?:elimina|elmina|elminar|borra|borrar|suprime|lee|muestra)\s+el\s+archivo\s+(\S+)\s+(?:de\s+la\s+carpeta\s+|de\s+|en\s+la\s+carpeta\s+|en\s+)(\S+)", msg_clean, re.IGNORECASE)
    if m:
        filename = m.group(1).strip()
        folder = m.group(2).strip()
        folder_res = resolve_path(folder)
        
        final_filename = filename
        try:
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

    m = re.search(r"\b(?:añade|añde|anade|agrega|escribe|escribir)\s+(?:a\s+|en\s+)(?:el\s+archivo\s+)?(\S+)\s+(.+)", msg_clean, re.IGNORECASE)
    if not m:
        m = re.search(r"\bal\s+archivo\s+(\S+)\s+(?:añade|añde|anade|agrega|escribe)\s+(.+)", msg_clean, re.IGNORECASE)
        
    if m:
        filename = m.group(1).strip()
        content = m.group(2).strip()
        return {"tool": "append_file", "args": {"path": resolve_path(filename), "content": content}}

    m = re.search(r"\b(?:crea|escribir|escribe)\s+(?:un\s+archivo\s+|el\s+archivo\s+)?(?:en\s+la\s+ruta\s+|en\s+)?(\S+)\s+(?:que\s+diga|con\s+contenido)\s+(.+)", msg_clean, re.IGNORECASE)
    if m:
        filename = m.group(1).strip()
        content = m.group(2).strip()
        
        folder = None
        if any(x in msg_clean.lower() for x in ["esta carpeta", "este directorio", "esa carpeta"]):
            for h in reversed(history):
                try:
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
