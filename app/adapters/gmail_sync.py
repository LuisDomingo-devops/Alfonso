"""
gmail_sync.py — Módulo para sincronizar correos reales desde Gmail a través de IMAP de forma asíncrona no bloqueante.
"""

import os
import imaplib
import email
import asyncio
from email.header import decode_header
from app.adapters.mail_db import create_email, get_connection

def clean_header(header_value) -> str:
    if not header_value:
        return ""
    decoded = decode_header(header_value)
    parts = []
    for val, charset in decoded:
        if isinstance(val, bytes):
            if charset:
                try:
                    parts.append(val.decode(charset, errors="ignore"))
                except Exception:
                    parts.append(val.decode("utf-8", errors="ignore"))
            else:
                parts.append(val.decode("utf-8", errors="ignore"))
        else:
            parts.append(val)
    return "".join(parts)


def _sync_from_gmail_blocking() -> int:
    import socket
    socket.setdefaulttimeout(3.0)
    from dotenv import load_dotenv
    load_dotenv()
    gmail_user = os.getenv("GMAIL_EMAIL")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pass:
        return 0
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")
        
        from datetime import datetime, timedelta
        since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'(SINCE "{since_date}")')
        
        if status != "OK" or not messages[0]:
            mail.close()
            mail.logout()
            return 0
            
        email_ids = messages[0].split()
        inserted_count = 0
        
        conn = get_connection()
        try:
            # Procesar últimos 30 correos para rapidez
            for e_id in reversed(email_ids[-30:]):
                status, data = mail.fetch(e_id, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                    
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                subject = clean_header(msg["Subject"])
                sender = clean_header(msg["From"])
                recipient = clean_header(msg["To"])
                
                date_str = msg["Date"]
                try:
                    received_dt = email.utils.parsedate_to_datetime(date_str)
                    received_at = received_dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    received_at = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                exists = conn.execute(
                    "SELECT 1 FROM emails WHERE sender = ? AND subject = ? AND received_at = ?",
                    (sender, subject, received_at)
                ).fetchone()
                
                if exists:
                    continue
                    
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="ignore")
                            break
                        elif content_type == "text/html" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            html_content = payload.decode(charset, errors="ignore")
                            from html.parser import HTMLParser
                            class Stripper(HTMLParser):
                                def __init__(self):
                                    super().__init__()
                                    self.reset()
                                    self.fed = []
                                def handle_data(self, d):
                                    self.fed.append(d)
                                def get_data(self):
                                    return "".join(self.fed)
                            s = Stripper()
                            s.feed(html_content)
                            body = s.get_data()
                else:
                    payload = msg.get_payload(decode=True)
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="ignore")
                    
                status, flag_data = mail.fetch(e_id, "(FLAGS)")
                read_status = 1
                if flag_data and b"\\Seen" not in flag_data[0]:
                    read_status = 0
                    
                # Guardar en base de datos local
                cursor = conn.execute(
                    """
                    INSERT INTO emails (sender, recipient, subject, body, received_at, category, importance, read_status, summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sender, recipient, subject, body, received_at, None, "Media", read_status, None)
                )
                inserted_count += 1
            conn.commit()
        finally:
            conn.close()
            
        mail.close()
        mail.logout()
        return inserted_count
    except Exception as e:
        print(f"[ERROR] Error al sincronizar con Gmail: {e}")
        return 0


async def sync_from_gmail() -> int:
    return await asyncio.to_thread(_sync_from_gmail_blocking)
