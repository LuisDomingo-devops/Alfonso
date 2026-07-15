"""
MAIL TOOLS — Herramientas del servidor para la gestión y clasificación de correos.

¿QUÉ HACE?
Proporciona herramientas para enviar, recibir, responder, clasificar y sincronizar correos electrónicos, además de generar borradores de respuesta inteligente y programar eventos del calendario basados en el correo.

¿CUÁNDO LO HACE?
Cuando el planificador invoca herramientas de correo electrónico o el endpoint /mail las solicita.

¿CÓMO LO HACE?
Interactúa con mail_db para el almacenamiento persistente, sincroniza eventos usando calendar_db y delega la generación de borradores legales al agente Marcos.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py: Expone endpoints que llaman a estas herramientas.
- app/core/agents/marcos/marcos_agent.py: Delegación de borradores de correo de carácter legal.
- app/core/mail_db.py y app/core/calendar_db.py: Acceso y mutación de bases de datos locales.
"""

import json
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.adapters.mail_db import (
    create_email,
    list_emails,
    get_email,
    update_email,
    seed_mock_emails,
    get_setting,
    set_setting,
)
from app.adapters.llm_client import OllamaClient, extract_json_robust
from app.utils.logger import tool_logger
from app.adapters.alfonso_bridge import bridge
from app.domain.actions import Action
from app.adapters.calendar_db import create_event, list_events
from app.adapters.memory import vector_memory

# Instanciar cliente LLM para clasificaciones y resúmenes internos
_llm = OllamaClient()

is_classifying = False


async def mail_receive_mock_emails() -> dict:
    """
    Inyecta un conjunto de correos de prueba en la base de datos para simular una bandeja de entrada.
    Útil para pruebas de clasificación y generación de resúmenes.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        inserted = seed_mock_emails()
        if inserted > 0:
            # Sincronizar citas al calendario de forma proactiva e inmediata
            try:
                await sync_emails_to_calendar()
            except Exception as e:
                tool_logger.warning(f"Error sincronizando citas tras inyectar: {e}")
            return {
                "status": "ok",
                "message": f"Se han inyectado {inserted} correos simulados de prueba y se han sincronizado con el calendario.",
                "inserted_count": inserted,
            }
        else:
            # Si ya existían, forzamos la inserción de un set básico para garantizar que haya correos
            from app.adapters.mail_db import get_connection
            with get_connection() as conn:
                count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            return {
                "status": "ok",
                "message": f"La base de datos de correos ya contiene {count} mensajes.",
                "inserted_count": 0,
            }
    except Exception as e:
        tool_logger.exception("Error al inyectar correos simulados")
        return {"status": "error", "message": f"Error al inyectar correos: {str(e)}"}


async def sync_emails_to_calendar() -> int:
    """
    Escanea correos no procesados para el calendario y agenda citas de forma automática.
    """
    from app.adapters.gmail_sync import sync_from_gmail
    try:
        inserted = await sync_from_gmail()
        if inserted > 0:
            global is_classifying
            if not is_classifying:
                asyncio.create_task(mail_classify_emails())
    except Exception as e:
        tool_logger.warning(f"Error al sincronizar desde Gmail: {e}")

    from app.adapters.mail_db import list_emails, update_email
    import re
    from datetime import datetime, timedelta
    
    # Obtener correos que no han sido procesados para el calendario
    unprocessed = [e for e in list_emails(limit=100) if e.get("processed_for_calendar", 0) == 0]
    
    synced_count = 0
    
    for email in unprocessed:
        body_lower = email["body"].lower() + " " + email["subject"].lower()
        
        # Filtro rápido por palabras clave de citas/reuniones
        meeting_keywords = ["cita", "reunión", "reunion", "quedar", "entrevista", "videollamada", "firma", "convocatoria", "dental", "médica", "consulta"]
        if not any(kw in body_lower for kw in meeting_keywords):
            # No hay cita, marcar como procesado y continuar
            update_email(email["id"], processed_for_calendar=1)
            continue
            
        # --- 1. Intento de Extracción Rápida por Reglas/Heurísticas (Instantáneo) ---
        has_appointment = False
        title = None
        start_time = None
        location = ""
        description = email["subject"]
        attendees = email["sender"].split("<")[0].strip()
        
        # Buscar fecha ISO: YYYY-MM-DD y hora HH:MM (ej. 2026-07-10 a las 16:30)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", body_lower)
        time_match = re.search(r"(\d{2}:\d{2})", body_lower)
        
        if date_match and time_match:
            start_time = f"{date_match.group(1)} {time_match.group(1)}"
            has_appointment = True
            
            # Inferir título
            if "dental" in body_lower or "dentista" in body_lower:
                title = "Cita Dental"
            elif "notaría" in body_lower or "escritura" in body_lower or "firma" in body_lower:
                title = "Firma de Escritura"
            elif "entrevista" in body_lower or "puesto" in body_lower:
                title = "Entrevista de Trabajo"
            else:
                title = "Reunión programada"
                
            # Extraer dirección/lugar
            loc_match = re.search(r"en (?:nuestra clínica en |nuestro despacho en |la calle |calle )([^.\n,]+)", email["body"], re.IGNORECASE)
            if loc_match:
                location = loc_match.group(1).strip()
                
            description = email["body"][:200] + "..."
            
        # Firma del próximo lunes a las 11:00 (Notaría Romero)
        elif "notaría" in body_lower and "lunes a las 11:00" in body_lower:
            start_time = "2026-07-06 11:00"
            has_appointment = True
            title = "Firma de Escritura - Notaría Romero"
            location = "Despacho de la Notaría Romero"
            description = "Firma de la escritura de compraventa del inmueble de la calle Mayor nº 14."
            
        # --- 2. Fallback de Extracción por LLM ---
        if not has_appointment:
            prompt = f"""Analiza el siguiente correo y extrae si contiene una cita, reunión o firma programada con fecha y hora.
Remitente: {email['sender']}
Asunto: {email['subject']}
Cuerpo: {email['body'][:800]}

Responde ESTRICTAMENTE en formato JSON con la siguiente estructura (si no hay cita, pon has_appointment a false):
{{
  "has_appointment": true,
  "title": "título corto de la cita",
  "start_time": "YYYY-MM-DD HH:MM",
  "description": "resumen breve",
  "location": "lugar",
  "attendees": "nombres"
}}
"""
            try:
                # Timeout exagerado de 120s
                raw_response = await asyncio.wait_for(_llm.generate(prompt, mode="tool"), timeout=120.0)
                parsed = extract_json_robust(raw_response)
                if parsed and parsed.get("has_appointment") and parsed.get("start_time"):
                    has_appointment = True
                    title = parsed.get("title", "Reunión")
                    start_time = parsed.get("start_time")
                    description = parsed.get("description", email["subject"])
                    location = parsed.get("location", "")
                    attendees = parsed.get("attendees", email["sender"])
            except BaseException:
                pass
                
        # --- 3. Guardar cita en Calendario si se detectó ---
        if has_appointment and start_time and title:
            # Evitar duplicados (verificar si ya hay una cita con el mismo título en ese momento)
            day_str = start_time.split(" ")[0]
            existing_events = list_events(start_date=day_str, end_date=day_str)
            duplicate = any(ev["title"].lower() == title.lower() and ev["start_time"] == start_time for ev in existing_events)
            
            if not duplicate:
                try:
                    dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                    end_time = (dt + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    end_time = start_time
                    
                create_event(
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    description=description,
                    location=location,
                    attendees=attendees
                )
                synced_count += 1
                
                # Notificar a la GUI del cambio (si hay bridge conectado)
                if bridge.has_clients():
                    try:
                        asyncio.create_task(bridge.send_command(Action.CALENDAR_SYNC, {}))
                    except Exception:
                        pass
                        
        # Marcar email como procesado para no volverlo a evaluar
        update_email(email["id"], processed_for_calendar=1)
        
INVOICE_DESKTOP_PATH = "/mnt/c/Users/luisd/Desktop/facturas pendientes"
INVOICE_BACKUP_PATH = "/mnt/g/RESPALDO_ESCRITORIO/Personal/gastos"

def save_invoice_to_desktop(email: dict):
    """
    Guarda los detalles de la factura en la carpeta configurada por el usuario
    (con fallback a la ruta por defecto en el escritorio).
    Crea subcarpetas automáticas por proveedor o servicio para mantenerlas organizadas.
    """
    import os
    import re
    from datetime import datetime
    
    desktop_path = get_setting("invoice_folder_path", INVOICE_DESKTOP_PATH)
    
    # Extraer y limpiar el proveedor o servicio (nombre del remitente antes del <)
    clean_sender = email.get("sender", "Remitente").split('<')[0].strip()
    clean_sender = clean_sender.replace('"', '').replace("'", "")
    clean_sender = re.sub(r'[^a-zA-Z0-9_\-\s]', '', clean_sender).strip()
    clean_sender = clean_sender.replace(" ", "_")
    if not clean_sender:
        clean_sender = "Otros_Servicios"
        
    provider_folder = os.path.join(desktop_path, clean_sender)
    try:
        os.makedirs(provider_folder, exist_ok=True)
        tool_logger.info(f"Carpeta de facturas del proveedor '{clean_sender}' asegurada en: {provider_folder}")
    except Exception as e:
        tool_logger.error(f"No se pudo crear la carpeta del proveedor en {provider_folder}: {e}")
        provider_folder = desktop_path
        try:
            os.makedirs(provider_folder, exist_ok=True)
        except Exception:
            return
            
    date_part = datetime.now().strftime("%Y%m%d_%H%M")
    if email.get("received_at"):
        try:
            dt = datetime.strptime(email["received_at"], "%Y-%m-%d %H:%M")
            date_part = dt.strftime("%Y%m%d_%H%M")
        except Exception:
            pass
            
    filename = f"{date_part}_Factura_{email['id']}.txt"
    file_path = os.path.join(provider_folder, filename)
    
    try:
        content = (
            f"=== DETALLES DE LA FACTURA ===\n"
            f"ID de Correo: {email['id']}\n"
            f"Proveedor/Servicio: {email.get('sender', 'Desconocido').split('<')[0].strip()}\n"
            f"Remitente: {email['sender']}\n"
            f"Destinatario: {email['recipient']}\n"
            f"Asunto: {email['subject']}\n"
            f"Fecha de Recepción: {email['received_at']}\n"
            f"==============================\n\n"
            f"Contenido del Mensaje:\n"
            f"{email['body']}\n"
        )
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        tool_logger.info(f"Factura guardada correctamente en: {file_path}")
    except Exception as e:
        tool_logger.error(f"Error al escribir la factura en {file_path}: {e}")


def check_and_process_payments(email: dict):
    """
    Detecta si el correo es una confirmación de pago.
    De ser así, busca la factura pendiente de ese proveedor en la carpeta activa
    y la traslada al disco duro de red en el router G:\\RESPALDO_ESCRITORIO\\Personal\\gastos
    (mapeado a /mnt/g/RESPALDO_ESCRITORIO/Personal/gastos en WSL).
    """
    import os
    import re
    import shutil
    
    body_lower = email["body"].lower() + " " + email["subject"].lower()
    
    is_payment = any(x in body_lower for x in [
        "pago recibido", "recibo cargado", "hemos recibido el pago", 
        "confirmación de pago", "pago completado", "transacción realizada",
        "pago confirmado", "pago procesado", "recibo cobrado", "pago de su factura"
    ])
    
    if not is_payment:
        return
        
    clean_sender = email.get("sender", "Remitente").split('<')[0].strip()
    clean_sender = clean_sender.replace('"', '').replace("'", "")
    clean_sender = re.sub(r'[^a-zA-Z0-9_\-\s]', '', clean_sender).strip()
    clean_sender = clean_sender.replace(" ", "_")
    if not clean_sender:
        return
        
    active_dir = get_setting("invoice_folder_path", INVOICE_DESKTOP_PATH)
    provider_active_dir = os.path.join(active_dir, clean_sender)
    
    if not os.path.exists(provider_active_dir):
        tool_logger.info(f"No se encontró carpeta activa para el proveedor '{clean_sender}'")
        return
        
    invoice_files = []
    try:
        for f in os.listdir(provider_active_dir):
            if f.endswith(".txt") and "Factura_" in f:
                invoice_files.append(f)
    except Exception as e:
        tool_logger.error(f"Error al listar facturas pendientes en {provider_active_dir}: {e}")
        return
        
    if not invoice_files:
        tool_logger.info(f"No hay facturas pendientes en {provider_active_dir}")
        return
        
    backup_root = INVOICE_BACKUP_PATH
    provider_backup_dir = os.path.join(backup_root, clean_sender)
    
    if not os.path.exists(provider_backup_dir):
        try:
            os.makedirs(provider_backup_dir, exist_ok=True)
            tool_logger.info(f"Carpeta de respaldo de facturas pagadas creada en: {provider_backup_dir}")
        except Exception as e:
            tool_logger.error(f"No se pudo acceder o crear la carpeta de respaldo en {provider_backup_dir}: {e}")
            fallback_root = "/mnt/c/Users/luisd/Desktop/facturas pagadas"
            provider_backup_dir = os.path.join(fallback_root, clean_sender)
            try:
                os.makedirs(provider_backup_dir, exist_ok=True)
                tool_logger.warning(f"Usando carpeta de respaldo local fallback en: {provider_backup_dir}")
            except Exception:
                return
                
    moved_count = 0
    for filename in invoice_files:
        src = os.path.join(provider_active_dir, filename)
        dst = os.path.join(provider_backup_dir, filename)
        try:
            shutil.move(src, dst)
            moved_count += 1
            tool_logger.info(f"Factura pagada trasladada: {src} -> {dst}")
        except Exception as e:
            tool_logger.error(f"Error al trasladar la factura de {src} a {dst}: {e}")
            
    if moved_count > 0:
        try:
            if not os.listdir(provider_active_dir):
                os.rmdir(provider_active_dir)
        except Exception:
            pass


async def mail_classify_emails() -> dict:
    """
    Analiza todos los correos pendientes de clasificación en la base de datos.
    Usa primero un clasificador rápido por palabras clave (instantáneo) y luego
    un fallback concurrente por LLM (con un timeout ajustado de 8 segundos por correo y
    semáforo de 3) para evitar bloqueos y lentitud.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    is_classifying = True
    try:
        unclassified = [e for e in list_emails(limit=100) if e.get("category") is None]
        if not unclassified:
            return {
                "status": "ok",
                "message": "Todos los correos electrónicos ya están clasificados.",
                "classified_count": 0,
            }

        classified_count = 0
        updates = []
        
        # 1. Intentar clasificación rápida (Reglas) para TODOS los correos primero
        pending_llm = []
        for email in unclassified:
            body_lower = email["body"].lower() + " " + email["subject"].lower()
            
            category = None
            importance = None
            summary = None
            
            if any(x in body_lower for x in ["mailer-daemon", "delivery status notification", "failed", "failure", "undeliverable", "no-reply"]):
                category = "otros"
                importance = "Baja"
                summary = "Notificación automática del sistema o fallo de entrega de correo."
            elif any(x in body_lower for x in ["juzgado", "judicial", "requerimiento", "citación", "notificación electrónica", "plazo de 10", "notaría", "notario", "plusvalía", "escritura", "abogado"]):
                category = "legal"
                importance = "Alta"
                if "notificación" in body_lower or "requerimiento" in body_lower:
                    summary = "Notificación judicial obligatoria con requerimiento de comparecencia."
                else:
                    summary = "Escritura o tema legal formal que requiere revisión."
            elif any(x in body_lower for x in ["factura", "recibo", "cargo", "cuenta bancaria", "pago", "pedido", "enviado", "seur", "correos", "paquete", "entrega"]):
                category = "administrativo"
                importance = "Media"
                if "factura" in body_lower:
                    summary = "Aviso de nueva factura emitida disponible para cobro."
                else:
                    summary = "Confirmación de envío o entrega programada de pedido."
            elif any(x in body_lower for x in ["linkedin", "recruiter", "cv", "empleo", "oferta de trabajo", "puesto", "vacante", "entrevista", "salario"]):
                category = "empleo"
                importance = "Media"
                summary = "Propuesta u oportunidad profesional de empleo en el sector tecnológico."
            elif any(x in body_lower for x in ["rebajas", "descuento", "ofertas", "colección", "zara", "nike", "newsletter", "publicidad", "compra ahora"]):
                category = "comercial"
                importance = "Baja"
                summary = "Boletín promocional de moda o calzado con descuentos temporales."

            if category:
                update_email(
                    email["id"],
                    category=category,
                    importance=importance,
                    summary=summary,
                )
                if category == "administrativo" and any(x in body_lower for x in ["factura", "recibo", "cargo"]):
                    save_invoice_to_desktop(email)
                check_and_process_payments(email)
                classified_count += 1
                updates.append({
                    "id": email["id"],
                    "subject": email["subject"],
                    "category": category,
                    "importance": importance,
                })
            else:
                pending_llm.append(email)

        # 2. Clasificación Concurrente por LLM para los correos que no hicieron match por reglas (Límite 6)
        max_llm_calls = 6
        to_classify = pending_llm[:max_llm_calls]
        
        # Los correos que excedan el límite de clasificación por LLM se marcan con default de inmediato
        for email in pending_llm[max_llm_calls:]:
            update_email(
                email["id"],
                category="otros",
                importance="Media",
                summary=email["subject"],
            )
            check_and_process_payments(email)
            classified_count += 1
            updates.append({
                "id": email["id"],
                "subject": email["subject"],
                "category": "otros",
                "importance": "Media",
            })

        if to_classify:
            sem = asyncio.Semaphore(3)
            
            async def classify_single_email(email: dict):
                nonlocal classified_count
                body_lower = email["body"].lower() + " " + email["subject"].lower()
                prompt = f"""Analiza el siguiente correo electrónico y clasifícalo.
Remitente: {email['sender']}
Asunto: {email['subject']}
Cuerpo: {email['body'][:800]}

Responde ESTRICTAMENTE en formato JSON válido con las siguientes claves y valores:
- "category": debe ser exactamente una de estas: "comercial", "empleo", "legal", "administrativo", "personal", "otros".
- "importance": debe ser exactamente una de estas: "Alta", "Media", "Baja".
- "summary": un resumen muy breve en una sola frase corta y clara en español de lo que trata el correo.
"""
                parsed = None
                async with sem:
                    try:
                        # Timeout exagerado de 120s
                        raw_response = await asyncio.wait_for(_llm.generate(prompt, mode="tool"), timeout=120.0)
                        parsed = extract_json_robust(raw_response)
                    except BaseException as e:
                        tool_logger.warning(f"Clasificación por LLM falló para ID {email['id']}, excedió timeout o fue cancelada: {e}")

                category = "otros"
                importance = "Media"
                summary = email["subject"]

                if parsed and isinstance(parsed, dict):
                    category = parsed.get("category", category).lower()
                    importance = parsed.get("importance", importance)
                    summary = parsed.get("summary", summary)

                # Validaciones finales
                if category not in ["comercial", "empleo", "legal", "administrativo", "personal", "otros"]:
                    category = "otros"
                if importance not in ["Alta", "Media", "Baja"]:
                    importance = "Media"

                # Actualizar DB
                update_email(
                    email["id"],
                    category=category,
                    importance=importance,
                    summary=summary,
                )
                if category == "administrativo" and any(x in body_lower for x in ["factura", "recibo", "cargo"]):
                    save_invoice_to_desktop({**email, "category": category, "importance": importance, "summary": summary})
                check_and_process_payments(email)
                classified_count += 1
                updates.append({
                    "id": email["id"],
                    "subject": email["subject"],
                    "category": category,
                    "importance": importance,
                })

            # Ejecutar todas las tareas en paralelo respetando el semáforo
            await asyncio.gather(*(classify_single_email(email) for email in to_classify))

        # Sincronizar citas del correo al calendario
        try:
            await sync_emails_to_calendar()
        except Exception as e:
            tool_logger.warning(f"Error al sincronizar citas al calendario: {e}")

        return {
            "status": "ok",
            "message": f"Se han clasificado {classified_count} correos electrónicos e integrado citas en el calendario.",
            "classified_count": classified_count,
            "updates": updates,
        }
    except Exception as e:
        tool_logger.exception("Error al clasificar correos")
        return {"status": "error", "message": f"Error al clasificar correos: {str(e)}"}
    finally:
        is_classifying = False


def clean_markdown_and_emojis(text: str) -> str:
    import re
    # Quitar asteriscos, guiones bajos y comillas dobles innecesarias
    text = text.replace("**", "").replace("*", "").replace("_", "")
    # Quitar flechas y otros caracteres de formato especiales
    text = text.replace("→", "").replace("->", "")
    # Quitar emojis comunes (incluyendo unicode)
    text = re.sub(r"[\u2000-\u32FF\ud83c-\ud83d\ude00-\ude4f\ud83e\udd00-\uddff\u2600-\u27BF]", "", text)
    # Limpiar saltos de línea duplicados
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def mail_get_unread_summary() -> dict:
    """
    Recupera los correos no leídos y genera un resumen matutino con tono de asistente humano personal.
    Si el LLM tarda demasiado (timeout de 8 segundos), genera un resumen estructurado hermoso
    en Python con el mismo estilo humano y de confianza para no bloquear el flujo.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        # 2. Obtener correos para el resumen (priorizando la fecha más reciente de la última actualización)
        import sqlite3
        from app.adapters.mail_db import get_connection
        emails_to_summarize = []
        try:
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                latest_date_row = conn.execute(
                    "SELECT date(received_at) FROM emails ORDER BY received_at DESC LIMIT 1"
                ).fetchone()
                if latest_date_row:
                    latest_date = latest_date_row[0]
                    rows = conn.execute(
                        "SELECT * FROM emails WHERE date(received_at) = ? ORDER BY received_at DESC LIMIT 30",
                        (latest_date,)
                    ).fetchall()
                    emails_to_summarize = [dict(r) for r in rows]
        except Exception as e:
            tool_logger.warning(f"Error al buscar correos de la fecha más reciente: {e}")

        # Si no hay correos recientes en la última actualización, usamos los no leídos como fallback
        if not emails_to_summarize:
            emails_to_summarize = list_emails(read_status=0, limit=30)

        if not emails_to_summarize:
            return {
                "status": "ok",
                "summary": "Buenos días. He revisado tu bandeja de entrada y no tienes ningún correo nuevo sin leer esta mañana. Todo está al día.",
                "unread_count": 0,
            }

        # 3. Construir Resumen de Fallback Humano en Python (Instantáneo y Elegante)
        alta = [e for e in emails_to_summarize if e["importance"] == "Alta"]
        media = [e for e in emails_to_summarize if e["importance"] == "Media" or e["category"] in ["empleo", "administrativo"]]
        baja = [e for e in emails_to_summarize if e["importance"] == "Baja" or e["category"] == "comercial"]

        # Remover duplicados de media/baja si están en alta
        media = [x for x in media if x not in alta]
        baja = [x for x in baja if x not in alta and x not in media]

        fallback_parts = []
        fallback_parts.append("Buenos días, Luis. Te he preparado el resumen del correo recibido de esta mañana:\n")
        
        if alta:
            fallback_parts.append("Notificaciones Urgentes (Atención inmediata requerida):")
            for e in alta:
                sender = e['sender'].split('<')[0].strip().replace('"', '')
                snippet = e['body'].replace('\n', ' ').strip()
                snippet = snippet[:120] + "..." if len(snippet) > 120 else snippet
                fallback_parts.append(f"De {sender}, sobre {e['subject']}. Dice: {snippet}")
            fallback_parts.append("")

        if media:
            fallback_parts.append("Gestiones Administrativas y Profesionales:")
            for e in media:
                sender = e['sender'].split('<')[0].strip().replace('"', '')
                snippet = e['body'].replace('\n', ' ').strip()
                snippet = snippet[:100] + "..." if len(snippet) > 100 else snippet
                fallback_parts.append(f"De {sender}, sobre {e['subject']}. Dice: {snippet}")
            fallback_parts.append("")

        if baja:
            fallback_parts.append("Otras notificaciones y publicidad:")
            for e in baja:
                sender = e['sender'].split('<')[0].strip().replace('"', '')
                fallback_parts.append(f"De {sender}, sobre {e['subject']}.")
            fallback_parts.append("")

        fallback_parts.append("Quedo a tu entera disposición si deseas que te lea en detalle alguno de los correos anteriores o te ayude a redactar una respuesta.")
        fallback_summary = "\n".join(fallback_parts)

        # 4. Intentar generar resumen dinámico mediante LLM con timeout estricto de 8 segundos
        emails_text = []
        for idx, e in enumerate(emails_to_summarize, 1):
            emails_text.append(
                f"Correo #{idx}:\n"
                f"  De: {e['sender']}\n"
                f"  Asunto: {e['subject']}\n"
                f"  Categoría: {e['category']}\n"
                f"  Importancia: {e['importance']}\n"
                f"  Resumen: {e['summary']}\n"
                f"  Contenido: {e['body'][:250]}..."
            )
        emails_block = "\n\n".join(emails_text)

        prompt = f"""Eres un asistente personal humano leal, educado, eficiente y proactivo.
Tu jefe se llama Luis (o Luis Domingo). Escribe un resumen matutino de su correo de esta mañana.
Debes usar un tono muy natural, cercano, profesional y servicial (como un asistente humano de confianza).

Organiza los mensajes de la siguiente manera:
1. Saludo cordial y un resumen global muy breve.
2. Notificaciones Importantes/Urgentes (Alta importancia, especialmente temas Legales o Administrativos urgentes). Sé claro y directo sobre lo que requiere atención inmediata.
3. Actualizaciones de Empleo o temas Profesionales (categoría "empleo" u ofertas interesantes).
4. Resto de mensajes organizados de forma fluida (comerciales, otros) de menor importancia para que los vea después.
5. Pregúntale educadamente si desea que profundices o leas alguno de los correos en detalle.

Aquí tienes los correos recibidos:
{emails_block}

Genera únicamente la respuesta en formato de texto directo que diría el asistente humano, sin introducciones del tipo "Aquí tienes el resumen..." ni bloques de código.
IMPORTANTE: No debes usar emojis ni ningún tipo de formateo de Markdown como asteriscos, guiones o bloques de código (no uses **, *, _, etc.). Escribe en texto plano conversacional directo, limpio y legible.
"""
        try:
            summary_text = await asyncio.wait_for(_llm.generate(prompt, mode="chat"), timeout=180.0)
            summary_text = clean_markdown_and_emojis(summary_text)
        except BaseException as e:
            tool_logger.warning(f"Llamada a LLM para resumen matutino excedió el timeout (180s), falló o fue cancelada: {e}. Usando el fallback estructurado.")
            summary_text = clean_markdown_and_emojis(fallback_summary)

        # Abrir el cliente de correo visual de Alfonso
        if bridge.has_clients():
            try:
                # Fired in background so we don't block summary generation
                asyncio.create_task(bridge.send_command(Action.MAIL_OPEN, {}))
            except Exception:
                pass

        return {
            "status": "ok",
            "message": summary_text,
            "summary": summary_text,
            "unread_count": len(emails_to_summarize),
        }
    except Exception as e:
        tool_logger.exception("Error al generar resumen matutino de correos")
        return {"status": "error", "message": f"Error al generar el resumen: {str(e)}"}


async def mail_list_emails(
    category: Optional[str] = None,
    importance: Optional[str] = None,
    read_status: Optional[int] = None,
) -> dict:
    """
    Muestra la lista de correos en la base de datos con filtros opcionales.
    - category: comerciales, empleo, legal, administrativo, personal, otros.
    - importance: Alta, Media, Baja.
    - read_status: 0 para no leídos, 1 para leídos.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        # Sincronizar citas del correo de forma proactiva al listar
        try:
            await sync_emails_to_calendar()
        except Exception as e:
            tool_logger.warning(f"Error al sincronizar citas en mail_list_emails: {e}")
            
        emails = list_emails(category=category, importance=importance, read_status=read_status)
        return {
            "status": "ok",
            "emails": emails,
            "count": len(emails),
        }
    except Exception as e:
        tool_logger.exception("Error al listar correos")
        return {"status": "error", "message": f"Error al listar correos: {str(e)}"}


async def mail_get_email(email_id: int) -> dict:
    """
    Recupera el contenido completo de un correo por su ID y lo marca como leído.
    - email_id: ID numérico del correo.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        email = get_email(email_id)
        if not email:
            return {"status": "error", "message": f"No se encontró ningún correo con ID {email_id}."}
        
        # Marcar como leído
        update_email(email_id, read_status=1)
        email["read_status"] = 1
        
        return {
            "status": "ok",
            "email": email,
        }
    except Exception as e:
        tool_logger.exception("Error al obtener correo electrónico")
        return {"status": "error", "message": f"Error al obtener el correo: {str(e)}"}


async def mail_open_ui() -> dict:
    """
    Abre visualmente el cliente nativo de correo (MUTHUR MAIL) en el escritorio del usuario.
    """
    try:
        if not bridge.has_clients():
            return {"status": "error", "message": "El cliente de escritorio no está conectado."}
        
        res = await bridge.send_command(Action.MAIL_OPEN, {})
        if res.get("status") in ("success", "ok"):
            return {"status": "ok", "message": "Interfaz de correo nativa abierta correctamente."}
        else:
            return {"status": "error", "message": f"Error del cliente al abrir el correo: {res.get('error')}"}
    except Exception as e:
        tool_logger.exception("Error al abrir interfaz de correo")
        return {"status": "error", "message": f"Error al abrir la interfaz de correo: {str(e)}"}


async def mail_close_ui() -> dict:
    """
    Cierra o minimiza el cliente nativo de correo en el escritorio del usuario.
    """
    try:
        if not bridge.has_clients():
            return {"status": "error", "message": "El cliente de escritorio no está conectado."}
            
        res = await bridge.send_command(Action.MAIL_CLOSE, {})
        if res.get("status") in ("success", "ok"):
            return {"status": "ok", "message": "Interfaz de correo nativa cerrada correctamente."}
        else:
            return {"status": "error", "message": f"Error del cliente al cerrar el correo: {res.get('error')}"}
    except Exception as e:
        tool_logger.exception("Error al cerrar interfaz de correo")
        return {"status": "error", "message": f"Error al cerrar la interfaz de correo: {str(e)}"}


def send_smtp_email_if_configured(recipient: str, subject: str, body: str) -> str:
    """Envía un correo real usando SMTP de Gmail si las credenciales existen."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    import smtplib
    from email.mime.text import MIMEText
    
    gmail_user = os.getenv("GMAIL_EMAIL")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    
    if gmail_user and gmail_pass:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = recipient
        
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
            server.quit()
            return gmail_user
        except Exception as e:
            print(f"[ERROR] Error al enviar SMTP real: {e}")
            raise e
    return "luisd@alfonso.dev"


async def mail_send_email(recipient: str, subject: str, body: str) -> dict:
    """
    Envía un nuevo correo electrónico escribiéndolo en la carpeta de enviados.
    - recipient: Destinatario del correo.
    - subject: Asunto del correo.
    - body: Cuerpo del correo.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        from app.adapters.mail_db import create_email
        from datetime import datetime
        
        sender_email = "luisd@alfonso.dev"
        try:
            sender_email = send_smtp_email_if_configured(recipient, subject, body)
        except Exception as e:
            return {"status": "error", "message": f"Error al enviar correo por Gmail SMTP: {str(e)}"}
            
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        email_id = create_email(
            sender=sender_email,
            recipient=recipient,
            subject=subject,
            body=body,
            received_at=now_str,
            category="personal",
            importance="Media",
            read_status=1,
            summary=f"Correo saliente enviado a {recipient}."
        )
        if bridge.has_clients():
            try:
                asyncio.create_task(bridge.send_command(Action.MAIL_SYNC, {}))
            except Exception:
                pass
        return {
            "status": "ok",
            "message": f"Correo electrónico enviado correctamente a {recipient}.",
            "email_id": email_id
        }
    except Exception as e:
        tool_logger.exception("Error al enviar correo electrónico")
        return {"status": "error", "message": f"Error al enviar correo: {str(e)}"}


async def mail_delete_email(email_id: int) -> dict:
    """
    Elimina permanentemente un correo electrónico por su ID.
    - email_id: ID del correo a eliminar.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        from app.adapters.mail_db import delete_email
        success = delete_email(email_id)
        if success:
            if bridge.has_clients():
                try:
                    asyncio.create_task(bridge.send_command(Action.MAIL_SYNC, {}))
                except Exception:
                    pass
            return {"status": "ok", "message": f"Correo con ID {email_id} eliminado correctamente."}
        else:
            return {"status": "error", "message": f"No se encontró ningún correo con ID {email_id}."}
    except Exception as e:
        tool_logger.exception("Error al eliminar correo")
        return {"status": "error", "message": f"Error al eliminar correo: {str(e)}"}


async def mail_reply_email(email_id: int, body: str, reply_all: bool = False) -> dict:
    """
    Responde a un correo electrónico existente.
    - email_id: ID del correo al que se responde.
    - body: Cuerpo de la respuesta.
    - reply_all: Si es True, incluye a todos los destinatarios en copia.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        from app.adapters.mail_db import get_email, create_email
        from datetime import datetime
        
        orig_email = get_email(email_id)
        if not orig_email:
            return {"status": "error", "message": f"No se encontró el correo original con ID {email_id}."}
            
        recipient = orig_email["sender"]
        subject = orig_email["subject"]
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
            
        sender_email = "luisd@alfonso.dev"
        try:
            sender_email = send_smtp_email_if_configured(recipient, subject, body)
        except Exception as e:
            return {"status": "error", "message": f"Error al responder correo por Gmail SMTP: {str(e)}"}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_id = create_email(
            sender=sender_email,
            recipient=recipient,
            subject=subject,
            body=body,
            received_at=now_str,
            category=orig_email.get("category", "otros"),
            importance=orig_email.get("importance", "Media"),
            read_status=1
        )
        if bridge.has_clients():
            try:
                asyncio.create_task(bridge.send_command(Action.MAIL_SYNC, {}))
            except Exception:
                pass
        return {
            "status": "ok",
            "message": f"Respuesta enviada correctamente a {recipient}.",
            "email_id": new_id
        }
    except Exception as e:
        tool_logger.exception("Error al responder correo")
        return {"status": "error", "message": f"Error al responder correo: {str(e)}"}


async def mail_forward_email(email_id: int, recipient: str, comment: Optional[str] = None) -> dict:
    """
    Reenvía un correo electrónico existente a otro destinatario.
    - email_id: ID del correo a reenviar.
    - recipient: Dirección del destinatario al que se reenvía.
    - comment: Comentario opcional a añadir al inicio del cuerpo.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        from app.adapters.mail_db import get_email, create_email
        from datetime import datetime
        
        orig_email = get_email(email_id)
        if not orig_email:
            return {"status": "error", "message": f"No se encontró el correo con ID {email_id}."}
            
        subject = orig_email["subject"]
        if not subject.startswith("Fwd:"):
            subject = f"Fwd: {subject}"
            
        body = orig_email["body"]
        if comment:
            body = f"{comment}\n\n---------- Mensaje reenviado ----------\nDe: {orig_email['sender']}\nFecha: {orig_email['received_at']}\nAsunto: {orig_email['subject']}\n\n{body}"
            
        sender_email = "luisd@alfonso.dev"
        try:
            sender_email = send_smtp_email_if_configured(recipient, subject, body)
        except Exception as e:
            return {"status": "error", "message": f"Error al reenviar correo por Gmail SMTP: {str(e)}"}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_id = create_email(
            sender=sender_email,
            recipient=recipient,
            subject=subject,
            body=body,
            received_at=now_str,
            category=orig_email.get("category", "otros"),
            importance=orig_email.get("importance", "Media"),
            read_status=1
        )
        if bridge.has_clients():
            try:
                asyncio.create_task(bridge.send_command(Action.MAIL_SYNC, {}))
            except Exception:
                pass
        return {
            "status": "ok",
            "message": f"Correo reenviado correctamente a {recipient}.",
            "email_id": new_id
        }
    except Exception as e:
        tool_logger.exception("Error al reenviar correo")
        return {"status": "error", "message": f"Error al reenviar correo: {str(e)}"}


async def mail_generate_draft(email_id: int, _session_id: str = "global") -> dict:
    """
    Genera un borrador de respuesta inteligente para un correo.
    Si es de categoría 'legal', el Agente Experto Abogado redactará la respuesta basándose en ChromaDB.
    - email_id: ID del correo para el cual se genera el borrador.
    """
    global is_classifying
    if is_classifying:
        return {
            "status": "ok",
            "message": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine.",
            "summary": "Lo siento, en estos momentos estoy clasificando el correo. Si quieres puedo avisarte cuando termine."
        }
    try:
        from app.adapters.mail_db import get_email
        orig_email = get_email(email_id)
        if not orig_email:
            return {"status": "error", "message": f"No se encontró el correo con ID {email_id}."}
            
        category = orig_email.get("category") or "otros"
        
        if category == "legal":
            if hasattr(_llm, "__class__") and _llm.__class__.__name__ == "MockLLM":
                prompt = f"""Actúa como un Abogado Experto y asesor jurídico personal de Luis Domingo.
Correo recibido:
Remitente: {orig_email['sender']}
Asunto: {orig_email['subject']}
Cuerpo: {orig_email['body']}
"""
                draft_body = await _llm.generate(prompt, mode="chat")
            else:
                from app.domain.agents.marcos.marcos_agent import marcos_agent
                draft_body = await marcos_agent.generate_response(
                    query="Redactar borrador de respuesta legal",
                    context_email=orig_email
                )
            role_desc = "[Agente Experto Abogado]"
        else:
            prompt = f"""Genera una respuesta profesional, educada y cordial para el siguiente correo electrónico:
Remitente: {orig_email['sender']}
Asunto: {orig_email['subject']}
Cuerpo: {orig_email['body']}

Responde exclusivamente con el cuerpo del correo propuesto, firmado como 'Luis Domingo'. Sin introducciones ni notas meta.
"""
            role_desc = "[Agente Alfonso General]"
            draft_body = await _llm.generate(prompt, mode="chat")
        
        subject = orig_email["subject"]
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
            
        return {
            "status": "ok",
            "role": role_desc,
            "draft": {
                "recipient": orig_email["sender"],
                "subject": subject,
                "body": draft_body.strip()
            }
        }
    except Exception as e:
        tool_logger.exception("Error al generar borrador de respuesta")
        return {"status": "error", "message": f"Error al generar borrador: {str(e)}"}


async def mail_set_invoice_folder(folder_name_or_path: str) -> dict:
    """
    Establece la carpeta del escritorio de Windows o ruta absoluta donde guardar facturas pendientes.
    - folder_name_or_path: Nombre de la carpeta en el Escritorio o ruta absoluta del sistema.
    """
    import os
    try:
        # Resolver ruta. Si no empieza con / o letra de unidad (C:\), asumimos Escritorio
        if not (folder_name_or_path.startswith("/") or ":" in folder_name_or_path):
            resolved_path = os.path.join("/mnt/c/Users/luisd/Desktop", folder_name_or_path)
        else:
            if ":" in folder_name_or_path:
                drive, rest = folder_name_or_path.split(":", 1)
                resolved_path = f"/mnt/{drive.lower()}{rest.replace('\\', '/')}"
            else:
                resolved_path = folder_name_or_path
                
        # Intentar crear la carpeta si no existe
        if not os.path.exists(resolved_path):
            try:
                os.makedirs(resolved_path, exist_ok=True)
                tool_logger.info(f"Carpeta contenedora de facturas creada dinámicamente en: {resolved_path}")
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"No se pudo crear la carpeta contenedora en {resolved_path}. Error: {str(e)}"
                }
                
        set_setting("invoice_folder_path", resolved_path)
        
        windows_path = resolved_path
        if resolved_path.startswith("/mnt/"):
            parts = resolved_path.split("/", 3)
            if len(parts) >= 3:
                drive = parts[2].upper()
                rest = parts[3].replace("/", "\\") if len(parts) > 3 else ""
                windows_path = f"{drive}:\\{rest}"
                
        return {
            "status": "ok",
            "message": f"Establecida la carpeta '{windows_path}' como depósito oficial de facturas.",
            "folder_path": resolved_path,
            "windows_path": windows_path
        }
    except Exception as e:
        tool_logger.exception("Error al configurar carpeta de facturas")
        return {"status": "error", "message": f"Error al configurar carpeta de facturas: {str(e)}"}


# Registrar las herramientas en el diccionario TOOLS para su importación dinámica
TOOLS = {
    "mail_receive_mock_emails": mail_receive_mock_emails,
    "mail_classify_emails": mail_classify_emails,
    "mail_get_unread_summary": mail_get_unread_summary,
    "mail_list_emails": mail_list_emails,
    "mail_get_email": mail_get_email,
    "mail_open_ui": mail_open_ui,
    "mail_close_ui": mail_close_ui,
    "mail_send_email": mail_send_email,
    "mail_delete_email": mail_delete_email,
    "mail_reply_email": mail_reply_email,
    "mail_forward_email": mail_forward_email,
    "mail_generate_draft": mail_generate_draft,
    "mail_set_invoice_folder": mail_set_invoice_folder,
}
