"""
MAIL DB — Abstracción de base de datos SQLite para correo electrónico.

¿QUÉ HACE?
Administra la base de datos local de correos electrónicos, ofreciendo filtros por importancia, remitente, y funciones para marcar como leído o sembrar datos simulados.

¿CUÁNDO LO HACE?
Al gestionar correos desde los endpoints HTTP o al invocar herramientas de clasificación y redacción.

¿CÓMO LO HACE?
Realizando operaciones SQL directas usando sqlite3 sobre una tabla local de correos persistidos.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py (expone los endpoints HTTP `/mail` para interactuar con esta base de datos)
- app/tools/mail_tools.py (utiliza estas funciones para enviar, clasificar y responder emails)
"""

import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

IS_TESTING = "pytest" in sys.modules or os.getenv("TESTING") == "true"

if IS_TESTING:
    DB_PATH = Path(__file__).resolve().parents[2] / "data" / "memory_test_mail.db"
else:
    DB_PATH = Path(__file__).resolve().parents[2] / "data" / "memory.db"

_db_initialized = False


def _init_mail_schema(conn: sqlite3.Connection) -> None:
    """Crea la tabla de emails e índices si no existen."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender      TEXT    NOT NULL,
            recipient   TEXT    NOT NULL,
            subject     TEXT    NOT NULL,
            body        TEXT    NOT NULL,
            received_at TEXT    NOT NULL, -- Formato ISO: YYYY-MM-DD HH:MM
            category    TEXT,             -- comercial, empleo, legal, administrativo, personal, otros
            importance  TEXT    NOT NULL DEFAULT 'Media', -- Alta, Media, Baja
            read_status INTEGER NOT NULL DEFAULT 0,       -- 0: No leído, 1: Leído
            summary     TEXT,
            processed_for_calendar INTEGER NOT NULL DEFAULT 0,
            notified    INTEGER NOT NULL DEFAULT 0,
            processed_for_job INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    try:
        conn.execute("ALTER TABLE emails ADD COLUMN processed_for_calendar INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE emails ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE emails ADD COLUMN processed_for_job INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_received_at
        ON emails (received_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_category
        ON emails (category)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()


def get_connection() -> sqlite3.Connection:
    global _db_initialized
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not _db_initialized:
        _init_mail_schema(conn)
        _db_initialized = True
    return conn


def create_email(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    received_at: str,
    category: Optional[str] = None,
    importance: str = "Media",
    read_status: int = 0,
    summary: Optional[str] = None,
) -> int:
    """Inserta un nuevo email en la base de datos."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO emails (sender, recipient, subject, body, received_at, category, importance, read_status, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sender, recipient, subject, body, received_at, category, importance, read_status, summary),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_email(email_id: int) -> Optional[Dict[str, Any]]:
    """Obtiene un email por su ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if row:
            return dict(row)
    finally:
        conn.close()
    return None


def list_emails(
    category: Optional[str] = None,
    importance: Optional[str] = None,
    read_status: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Lista correos aplicando filtros opcionales."""
    query = "SELECT * FROM emails WHERE 1=1"
    params = []

    if category is not None:
        query += " AND category = ?"
        params.append(category)
    else:
        query += " AND (category IS NULL OR (category != 'sent' AND category != 'draft'))"
    if importance is not None:
        query += " AND importance = ?"
        params.append(importance)
    if read_status is not None:
        query += " AND read_status = ?"
        params.append(read_status)

    query += " ORDER BY received_at DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_email(email_id: int, **kwargs) -> bool:
    """Actualiza campos específicos de un email."""
    if not kwargs:
        return False
    
    allowed_fields = {"category", "importance", "read_status", "summary", "processed_for_calendar", "processed_for_job"}
    set_clauses = []
    params = []
    
    for key, val in kwargs.items():
        if key in allowed_fields:
            set_clauses.append(f"{key} = ?")
            params.append(val)
            
    if not set_clauses:
        return False
        
    query = f"UPDATE emails SET {', '.join(set_clauses)} WHERE id = ?"
    params.append(email_id)
    
    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def seed_mock_emails() -> int:
    """Inserta correos simulados de prueba si no existen previamente en la base de datos."""
    mock_data = [
        {
            "sender": "Notificaciones Judiciales Madrid <notificaciones@justicia.madrid.es>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Notificación electrónica obligatoria Ref: EXP-2026/0491",
            "body": "Se le notifica que dispone de un plazo de 10 días hábiles para comparecer en la sede electrónica del Ministerio de Justicia en relación con el requerimiento judicial EXP-2026/0491 sobre el contrato de arrendamiento mercantil. En caso de no comparecer en plazo, se considerará notificado a todos los efectos legales.",
            "received_at": "2026-07-04 08:15",
            "category": None,
            "importance": "Alta",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Iberdrola Clientes <factura-no-reply@iberdrola.es>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Su factura de luz del periodo Mayo-Junio ya está disponible (68.42 €)",
            "body": "Estimado cliente: Le informamos de que ya puede consultar su última factura de electricidad con número de referencia IBER-9812-401 por un importe total de 68.42 Euros. El cargo se realizará en su cuenta bancaria habitual el día 10 de julio de 2026. Si desea reclamar o ver los detalles del consumo, acceda a su Área de Cliente.",
            "received_at": "2026-07-04 07:30",
            "category": None,
            "importance": "Media",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Recruiter LinkedIn <silvia.martinez@techsolutions-hr.com>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Propuesta Oportunidad Senior Python / AI Engineer - Remoto (100%)",
            "body": "Hola Luis, he estado revisando tu perfil en LinkedIn y veo que tienes una experiencia excelente liderando proyectos de agentes inteligentes y arquitecturas FastAPI. Actualmente estamos buscando un Senior Python / AI Lead para una startup en fase de crecimiento exponencial financiada por fondos internacionales de primer nivel. El salario oscila entre 65k-85k€ + equity. ¿Tendrías 15 minutos para charlar esta semana? Un saludo.",
            "received_at": "2026-07-04 09:00",
            "category": None,
            "importance": "Media",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Zara Fashion Newsletter <news@zara.es>",
            "recipient": "luisd@alfonso.dev",
            "subject": "¡Rebajas de Verano! Hasta -50% en toda la colección de hombre",
            "body": "No te pierdas las mejores ofertas de esta temporada. Descubre camisas de lino, pantalones de algodón y calzado deportivo con descuentos increíbles de hasta el 50% de descuento. Envío gratuito en compras superiores a 30 euros o recogida gratis en tu tienda más cercana. Oferta válida hasta fin de existencias.",
            "received_at": "2026-07-03 21:00",
            "category": None,
            "importance": "Baja",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Notaría Romero & Asociados <contacto@notariaromero.com>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Borrador de Escritura de compraventa - Revisión requerida urgente",
            "body": "Estimado Sr. Domingo: Adjuntamos el borrador definitivo de la escritura de compraventa del inmueble de la calle Mayor nº 14. Rogamos le preste especial atención a las cláusulas 4ª y 5ª sobre el reparto de gastos tributarios de plusvalía municipal antes de la firma del próximo lunes a las 11:00 en nuestro despacho. Atentamente.",
            "received_at": "2026-07-04 09:20",
            "category": None,
            "importance": "Alta",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Amazon.es <auto-confirm@amazon.es>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Confirmación de envío: Su pedido #403-91823-11 ya está en camino",
            "body": "Hola Luis, tu paquete que contiene 'Auriculares Inalámbricos con cancelación de ruido activa' ya ha sido enviado por el transportista SEUR y su entrega está programada para hoy antes de las 20:00. Puedes realizar el seguimiento en tiempo real a través del enlace de Amazon.",
            "received_at": "2026-07-04 06:10",
            "category": None,
            "importance": "Media",
            "read_status": 0,
            "summary": None,
        },
        {
            "sender": "Dr. Fernando García <citas@clinicadentalgarcia.com>",
            "recipient": "luisd@alfonso.dev",
            "subject": "Confirmación de su cita médica de revisión anual",
            "body": "Hola Luis, le confirmamos su cita para la revisión dental anual programada para el próximo 2026-07-10 a las 16:30 en nuestra clínica en Calle Mayor 12. Si desea modificar o cancelar la cita, por favor llame al teléfono de la clínica.",
            "received_at": "2026-07-05 10:00",
            "category": None,
            "importance": "Alta",
            "read_status": 0,
            "summary": None,
        }
    ]

    conn = get_connection()
    inserted = 0
    try:
        for data in mock_data:
            exists = conn.execute(
                "SELECT 1 FROM emails WHERE sender = ? AND subject = ?",
                (data["sender"], data["subject"])
            ).fetchone()
            if not exists:
                cursor = conn.execute(
                    """
                    INSERT INTO emails (sender, recipient, subject, body, received_at, category, importance, read_status, summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (data["sender"], data["recipient"], data["subject"], data["body"], data["received_at"], data["category"], data["importance"], data["read_status"], data["summary"]),
                )
                inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def delete_email(email_id: int) -> bool:
    """Elimina físicamente un correo de la base de datos por su ID."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Recupera un valor de configuración persistente por su clave."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    """Guarda o actualiza un valor de configuración persistente."""
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()
