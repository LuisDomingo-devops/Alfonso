"""
MEMORY — Memoria de diálogo y almacenamiento de historial.

¿QUÉ HACE?
Mantiene el historial de la conversación actual por sesión en memoria volátil (RAM).

¿CUÁNDO LO HACE?
Durante el procesamiento de consultas para recuperar mensajes previos del usuario y el asistente e inyectarlos en el prompt.

¿CÓMO LO HACE?
Almacenando listas de mensajes estructurados en un diccionario indexado por `session_id` con hilos seguros.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/domain/planner_orchestrator.py (consulta el historial para contextualizar al modelo)
- app/api/routes.py (ofrece endpoints para leer, listar y borrar historiales por sesión)
"""

import json
import os
import sqlite3
import sys
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List
from app.domain.ports.memory_port import MemoryPort

# 1. DETECCIÓN DE ENTORNO DE PRUEBAS
# Si se detecta pytest, usamos una base de datos temporal diferente (memory_test.db)
# para evitar colisiones con la base de datos de desarrollo y prevenir bloqueos.
IS_TESTING = "pytest" in sys.modules or os.getenv("TESTING") == "true"

if os.getenv("ALFONSO_DB_PATH"):
    DB_PATH = Path(os.getenv("ALFONSO_DB_PATH"))
elif IS_TESTING:
    DB_PATH = Path(__file__).resolve().parents[3] / "data" / "memory_test.db"
else:
    DB_PATH = Path(__file__).resolve().parents[3] / "data" / "memory.db"

# Variable de control para la inicialización perezosa (Lazy Initialization)
_db_initialized = False


def _init_db_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas e índices necesarios si no existen."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL,
            client_id   TEXT    NOT NULL DEFAULT 'default',
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_metadata (
            session_id   TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            discipline   TEXT NOT NULL DEFAULT 'general',
            project_name TEXT DEFAULT 'default',
            is_persistent INTEGER DEFAULT 1,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN client_id TEXT NOT NULL DEFAULT 'default'")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages (session_id, client_id, id)
    """)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    global _db_initialized
    
    if str(DB_PATH) != ":memory:":
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # 2. INICIALIZACIÓN PEREZOSA (LAZY INITIALIZATION)
    # En lugar de ejecutarse al importar el módulo, se ejecuta únicamente
    # cuando la aplicación (o un test) solicita la primera conexión real.
    if not _db_initialized or str(DB_PATH) == ":memory:":
        _init_db_schema(conn)
        _db_initialized = True
        
    return conn


class SessionMemory(MemoryPort):
    """
    Gestiona el historial de conversación por sesión.

    - Persiste en SQLite para sobrevivir reinicios.
    - Mantiene una caché en RAM (deque) para lecturas rápidas.
    - Aplica un límite max_messages: solo se guardan los N mensajes más recientes.
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        # Caché en RAM: session_id:client_id → deque de dicts {role, content}
        self._cache: Dict[str, Deque[Dict[str, str]]] = {}

    # ------------------------------------------------------------------
    # Caché
    # ------------------------------------------------------------------

    def _ensure_loaded(self, session_id: str, client_id: str | None = None) -> None:
        """Carga el historial desde SQLite si no está en caché."""
        cid = client_id or "default"
        cache_key = f"{session_id}:{cid}"
        if cache_key in self._cache:
            return

        with _get_connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = ? AND client_id = ?
                ORDER BY id ASC
                """,
                (session_id, cid),
            ).fetchall()

        self._cache[cache_key] = deque(
            [{"role": r["role"], "content": r["content"]} for r in rows],
            maxlen=self.max_messages,
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def add_message(self, session_id: str, role: str, content: str, client_id: str | None = None) -> None:
        if not session_id:
            return

        cid = client_id or "default"
        cache_key = f"{session_id}:{cid}"
        self._ensure_loaded(session_id, client_id)
        self._cache[cache_key].append({"role": role, "content": content})

        with _get_connection() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, client_id, role, content) VALUES (?, ?, ?, ?)",
                (session_id, cid, role, content),
            )
            # Borrar mensajes viejos que superen el límite
            conn.execute(
                """
                DELETE FROM messages
                WHERE session_id = ? AND client_id = ?
                  AND id NOT IN (
                      SELECT id FROM messages
                      WHERE session_id = ? AND client_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (session_id, cid, session_id, cid, self.max_messages),
            )
            conn.commit()

    def get_history(self, session_id: str, client_id: str | None = None) -> List[Dict[str, str]]:
        cid = client_id or "default"
        cache_key = f"{session_id}:{cid}"
        self._ensure_loaded(session_id, client_id)
        return list(self._cache.get(cache_key, []))

    def get_summary(self, session_id: str, client_id: str | None = None) -> str:
        history = self.get_history(session_id, client_id)
        if not history:
            return ""
        return "\n".join(f"{entry['role']}: {entry['content']}" for entry in history)

    def clear(self, session_id: str, client_id: str | None = None) -> None:
        cid = client_id or "default"
        cache_key = f"{session_id}:{cid}"
        self._cache.pop(cache_key, None)
        with _get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ? AND client_id = ?", (session_id, cid))
            conn.commit()

    def list_sessions(self, client_id: str | None = None) -> List[str]:
        """Devuelve todos los session_id con historial guardado."""
        cid = client_id or "default"
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM messages WHERE client_id = ? ORDER BY session_id",
                (cid,)
                ).fetchall()
        return [r["session_id"] for r in rows]

    def upsert_metadata(self, session_id: str, title: str, discipline: str = "general", project_name: str = "default", is_persistent: bool = True) -> None:
        """Crea o actualiza los metadatos de una conversación."""
        persistent_val = 1 if is_persistent else 0
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_metadata (session_id, title, discipline, project_name, is_persistent, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(session_id) DO UPDATE SET
                    title = excluded.title,
                    discipline = excluded.discipline,
                    project_name = excluded.project_name,
                    is_persistent = excluded.is_persistent,
                    updated_at = datetime('now')
                """,
                (session_id, title, discipline, project_name, persistent_val)
            )
            conn.commit()

    def get_metadata(self, session_id: str) -> dict | None:
        """Recupera los metadatos de una conversación."""
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT session_id, title, discipline, project_name, is_persistent, created_at, updated_at FROM conversation_metadata WHERE session_id = ?",
                (session_id,)
            ).fetchone()
        if row:
            return {
                "session_id": row["session_id"],
                "title": row["title"],
                "discipline": row["discipline"],
                "project_name": row["project_name"],
                "is_persistent": bool(row["is_persistent"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        return None

    def list_persistent_conversations(self) -> List[dict]:
        """Devuelve todas las conversaciones marcadas como persistentes."""
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT session_id, title, discipline, project_name, created_at, updated_at FROM conversation_metadata WHERE is_persistent = 1 ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# Instancia global compartida por toda la aplicación
memory = SessionMemory()
