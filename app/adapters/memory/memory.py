"""
MEMORY — Memoria de diálogo y almacenamiento de historial.

¿QUÉ HACE?
Mantiene el historial de la conversación actual por sesión en memoria volátil (RAM).

¿CUÁNDO LO HACE?
Durante el procesamiento de consultas para recuperar mensajes previos del usuario y el asistente e inyectarlos en el prompt.

¿CÓMO LO HACE?
Almacenando listas de mensajes estructurados en un diccionario indexado por `session_id` con hilos seguros.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/planner_orchestrator.py (consulta el historial para contextualizar al modelo)
- app/api/routes.py (ofrece endpoints para leer, listar y borrar historiales por sesión)
"""

import json
import os
import sqlite3
import sys
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List

# 1. DETECCIÓN DE ENTORNO DE PRUEBAS
# Si se detecta pytest, usamos una base de datos temporal diferente (memory_test.db)
# para evitar colisiones con la base de datos de desarrollo y prevenir bloqueos.
IS_TESTING = "pytest" in sys.modules or os.getenv("TESTING") == "true"

if IS_TESTING:
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
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages (session_id, id)
    """)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    global _db_initialized
    
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # 2. INICIALIZACIÓN PEREZOSA (LAZY INITIALIZATION)
    # En lugar de ejecutarse al importar el módulo, se ejecuta únicamente
    # cuando la aplicación (o un test) solicita la primera conexión real.
    if not _db_initialized:
        _init_db_schema(conn)
        _db_initialized = True
        
    return conn


class SessionMemory:
    """
    Gestiona el historial de conversación por sesión.

    - Persiste en SQLite para sobrevivir reinicios.
    - Mantiene una caché en RAM (deque) para lecturas rápidas.
    - Aplica un límite max_messages: solo se guardan los N mensajes más recientes.
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        # Caché en RAM: session_id → deque de dicts {role, content}
        self._cache: Dict[str, Deque[Dict[str, str]]] = {}

    # ------------------------------------------------------------------
    # Caché
    # ------------------------------------------------------------------

    def _ensure_loaded(self, session_id: str) -> None:
        """Carga el historial desde SQLite si no está en caché."""
        if session_id in self._cache:
            return

        with _get_connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        self._cache[session_id] = deque(
            [{"role": r["role"], "content": r["content"]} for r in rows],
            maxlen=self.max_messages,
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return

        self._ensure_loaded(session_id)
        self._cache[session_id].append({"role": role, "content": content})

        with _get_connection() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            # Borrar mensajes viejos que superen el límite
            conn.execute(
                """
                DELETE FROM messages
                WHERE session_id = ?
                  AND id NOT IN (
                      SELECT id FROM messages
                      WHERE session_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (session_id, session_id, self.max_messages),
            )
            conn.commit()

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        self._ensure_loaded(session_id)
        return list(self._cache.get(session_id, []))

    def get_summary(self, session_id: str) -> str:
        history = self.get_history(session_id)
        if not history:
            return ""
        return "\n".join(f"{entry['role']}: {entry['content']}" for entry in history)

    def clear(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
        with _get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_sessions(self) -> List[str]:
        """Devuelve todos los session_id con historial guardado."""
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM messages ORDER BY session_id"
                ).fetchall()
        return [r["session_id"] for r in rows]


# Instancia global compartida por toda la aplicación
memory = SessionMemory()
