import asyncio
import re
import sqlite3
from app.utils.logger import app_logger

async def start_background_mail_monitor(bridge_port=None):
    """
    Monitorea de forma periódica el correo de Gmail en segundo plano:
    Sincroniza correos, clasifica nuevos mensajes y notifica si se detectan urgentes.
    """
    app_logger.info("Iniciando monitor de correo en segundo plano (servicio desacoplado)...")
    await asyncio.sleep(15)
    
    from app.tools.server.mail_tools import sync_emails_to_calendar
    from app.adapters.mail_db import get_connection
    from app.domain.agents.job.job_agent import job_agent
    
    if bridge_port is None:
        from app.adapters.alfonso_bridge import bridge as bridge_port
        
    while True:
        try:
            # 1. Sincronizar y procesar en segundo plano
            await sync_emails_to_calendar()
            
            # 2. Buscar correos importantes (Alta) no leídos y que no hayan sido notificados aún
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, sender, subject FROM emails WHERE importance = 'Alta' AND read_status = 0 AND notified = 0"
                ).fetchall()
                
                for r in rows:
                    email_id = r["id"]
                    sender = r["sender"].split("<")[0].strip().replace('"', '').replace("'", "")
                    subject = r["subject"].replace("'", "")
                    
                    # Marcar como notificado
                    conn.execute("UPDATE emails SET notified = 1 WHERE id = ?", (email_id,))
                    conn.commit()
                    
                    app_logger.info(f"Notificando correo urgente ID {email_id} de {sender}")
                    
                    # Enviar comando de notificación si hay clientes conectados
                    if bridge_port.has_clients():
                        asyncio.create_task(bridge_port.send_command(
                            "system.notify",
                            {
                                "title": "⚠️ CORREO URGENTE",
                                "message": f"De: {sender}\nAsunto: {subject}"
                            }
                        ))
            
            # 3. Procesar correos de empleo para auto-postulación
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                job_rows = conn.execute(
                    "SELECT id, subject, body FROM emails WHERE category = 'empleo' AND processed_for_job = 0"
                ).fetchall()
                
                for jr in job_rows:
                    email_id = jr["id"]
                    body = jr["body"]
                    
                    # Extraer enlaces
                    urls = re.findall(r'(https?://[^\s<>"]+)', body)
                    
                    # Filtrar enlaces que parecen de ofertas reales
                    job_urls = [u for u in urls if any(k in u.lower() for k in ["oferta", "job", "empleo", "apply", "postula", "vacancy", "detail", "view", "linkedin.com/jobs"])]
                    
                    if job_urls:
                        target_url = job_urls[0]
                        app_logger.info(f"[BackgroundMonitor] Detectada oferta de empleo para procesar: {target_url} en correo ID {email_id}")
                        
                        try:
                            apply_res = await job_agent.auto_apply(target_url)
                            app_logger.info(f"[BackgroundMonitor] Auto-postulación completa para correo {email_id}: {apply_res}")
                        except Exception as e:
                            app_logger.error(f"[BackgroundMonitor] Fallo al auto-postularse en correo {email_id}: {e}")
                    
                    # Marcar como procesado para no repetir
                    conn.execute("UPDATE emails SET processed_for_job = 1 WHERE id = ?", (email_id,))
                    conn.commit()
                    
        except Exception as e:
            app_logger.warning(f"Error en monitor de correo de fondo: {e}")
            
        await asyncio.sleep(60) # Revisar cada 60 segundos
