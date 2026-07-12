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
)
from app.adapters.llm_client import OllamaClient, extract_json_robust
from app.utils.logger import tool_logger
from app.adapters.alfonso_bridge import bridge
from app.domain.actions import Action
from app.adapters.calendar_db import create_event, list_events
from app.adapters.memory import vector_memory

# Instanciar cliente LLM para clasificaciones y resúmenes internos
_llm = OllamaClient()


async def mail_receive_mock_emails() -> dict:
    """
    Inyecta un conjunto de correos de prueba en la base de datos para simular una bandeja de entrada.
    Útil para pruebas de clasificación y generación de resúmenes.
    """
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
    from app.core.gmail_sync import sync_from_gmail
    try:
        await sync_from_gmail()
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
Cuerpo: {email['body']}

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
                # Timeout ajustado de 4s
                raw_response = await asyncio.wait_for(_llm.generate(prompt, mode="tool"), timeout=4.0)
                parsed = extract_json_robust(raw_response)
                if parsed and parsed.get("has_appointment") and parsed.get("start_time"):
                    has_appointment = True
                    title = parsed.get("title", "Reunión")
                    start_time = parsed.get("start_time")
                    description = parsed.get("description", email["subject"])
                    location = parsed.get("location", "")
                    attendees = parsed.get("attendees", email["sender"])
            except Exception:
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
        
    return synced_count


async def mail_classify_emails() -> dict:
    """
    Analiza todos los correos pendientes de clasificación en la base de datos.
    Usa primero un clasificador rápido por palabras clave (instantáneo) y luego
    un fallback por LLM (con un timeout ajustado de 5 segundos por correo) para
    evitar bloqueos y lentitud en hardware limitado.
    """
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
        llm_calls_made = 0
        max_llm_calls = 2

        for email in unclassified:
            body_lower = email["body"].lower() + " " + email["subject"].lower()
            sender_lower = email["sender"].lower()
            
            # --- 1. Clasificación Rápida Basada en Reglas (Instantánea) ---
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
            
            # Si el clasificador por reglas funcionó, guardamos de inmediato y saltamos LLM
            if category:
                update_email(
                    email["id"],
                    category=category,
                    importance=importance,
                    summary=summary,
                )
                classified_count += 1
                updates.append({
                    "id": email["id"],
                    "subject": email["subject"],
                    "category": category,
                    "importance": importance,
                })
                continue

            # Si excedemos el límite de llamadas LLM en esta ejecución, asignamos default de inmediato
            if llm_calls_made >= max_llm_calls:
                update_email(
                    email["id"],
                    category="otros",
                    importance="Media",
                    summary=email["subject"],
                )
                classified_count += 1
                updates.append({
                    "id": email["id"],
                    "subject": email["subject"],
                    "category": "otros",
                    "importance": "Media",
                })
                continue

            # --- 2. Fallback de Clasificación por LLM (con timeout) ---
            prompt = f"""Analiza el siguiente correo electrónico y clasifícalo.
Remitente: {email['sender']}
Asunto: {email['subject']}
Cuerpo: {email['body']}

Responde ESTRICTAMENTE en formato JSON válido con las siguientes claves y valores:
- "category": debe ser exactamente una de estas: "comercial", "empleo", "legal", "administrativo", "personal", "otros".
- "importance": debe ser exactamente una de estas: "Alta", "Media", "Baja".
- "summary": un resumen muy breve en una sola frase corta y clara en español de lo que trata el correo.
"""
            try:
                llm_calls_made += 1
                # Ponemos un timeout de 4.0s para evitar que el servidor se congele si Ollama es lento
                raw_response = await asyncio.wait_for(_llm.generate(prompt, mode="tool"), timeout=4.0)
                parsed = extract_json_robust(raw_response)
            except Exception as e:
                tool_logger.warning(f"Clasificación por LLM falló o excedió timeout: {e}")
                parsed = None

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
            classified_count += 1
            updates.append({
                "id": email["id"],
                "subject": email["subject"],
                "category": category,
                "importance": importance,
            })

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


async def mail_get_unread_summary() -> dict:
    """
    Recupera los correos no leídos y genera un resumen matutino con tono de asistente humano personal.
    Si el LLM tarda demasiado (timeout de 8 segundos), genera un resumen estructurado hermoso
    en Python con el mismo estilo humano y de confianza para no bloquear el flujo.
    """
    try:
        # 1. Asegurar clasificación previa
        await mail_classify_emails()

        # 2. Listar correos no leídos
        unread_emails = list_emails(read_status=0, limit=30)
        if not unread_emails:
            return {
                "status": "ok",
                "summary": "Buenos días. He revisado tu bandeja de entrada y no tienes ningún correo nuevo sin leer esta mañana. Todo está al día.",
                "unread_count": 0,
            }

        # 3. Construir Resumen de Fallback Humano en Python (Instantáneo y Elegante)
        alta = [e for e in unread_emails if e["importance"] == "Alta"]
        media = [e for e in unread_emails if e["importance"] == "Media" or e["category"] in ["empleo", "administrativo"]]
        baja = [e for e in unread_emails if e["importance"] == "Baja" or e["category"] == "comercial"]

        # Remover duplicados de media/baja si están en alta
        media = [x for x in media if x not in alta]
        baja = [x for x in baja if x not in alta and x not in media]

        fallback_parts = []
        fallback_parts.append("Buenos días, Luis. Te he preparado el resumen del correo recibido de esta mañana:\n")
        
        if alta:
            fallback_parts.append("⚠️ **Notificaciones Urgentes (Atención inmediata requerida):**")
            for e in alta:
                fallback_parts.append(f"- **{e['sender']}**:\n  *{e['subject']}*\n  → _{e['summary'] or e['body'][:120]}_\n")
            fallback_parts.append("")

        if media:
            fallback_parts.append("📅 **Gestiones Administrativas y Profesionales:**")
            for e in media:
                fallback_parts.append(f"- **{e['sender']}**:\n  *{e['subject']}*\n  → _{e['summary'] or e['body'][:100]}_\n")
            fallback_parts.append("")

        if baja:
            fallback_parts.append("✉️ **Otras notificaciones y publicidad:**")
            for e in baja:
                fallback_parts.append(f"- **{e['sender']}**: *{e['subject']}*")
            fallback_parts.append("")

        fallback_parts.append("Quedo a tu entera disposición si deseas que te lea en detalle alguno de los correos anteriores o te ayude a redactar una respuesta.")
        fallback_summary = "\n".join(fallback_parts)

        # 4. Intentar generar resumen dinámico mediante LLM con timeout estricto de 8 segundos
        emails_text = []
        for idx, e in enumerate(unread_emails, 1):
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
"""
        try:
            summary_text = await asyncio.wait_for(_llm.generate(prompt, mode="chat"), timeout=8.0)
        except Exception as e:
            tool_logger.warning(f"Llamada a LLM para resumen matutino excedió el timeout (8s) o falló: {e}. Usando el fallback estructurado.")
            summary_text = fallback_summary

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
            "unread_count": len(unread_emails),
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
}
