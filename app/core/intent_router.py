"""
IntentRouter — Fase 1.

Mejoras respecto a la versión anterior:
- Patrones de append_file correctamente detectados.
- Penalización cuando el usuario dice "crea/escribe" SIN nombre de archivo
  (va a no_op en el prompt de tools, pero el intent sigue siendo tool para
  que el LLM decida correctamente).
- Mejor separación entre "escríbeme una carta" (chat) y
  "escribe el archivo notas.txt" (tool).
- Umbral subido ligeramente para reducir falsos positivos.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal

Intent = Literal["chat", "tool"]


@dataclass
class _Rule:
    pattern: re.Pattern
    weight: float
    category: str


def _r(pattern: str, weight: float, category: str) -> _Rule:
    return _Rule(re.compile(pattern, re.IGNORECASE), weight, category)


# ---------------------------------------------------------------------------
# Reglas positivas — indican que se necesita una tool
# ---------------------------------------------------------------------------
_TOOL_RULES: list[_Rule] = [
    # Filesystem — append (alta prioridad, evita confusión con create)
    _r(r"\b(añade|añadir|agrega|agregar|append)\b.{0,50}\b(archivo|fichero|al archivo|a ese archivo|al final|\.txt|\.py|\.json|\.csv|\.md)\b", 3.0, "fs_append"),
    _r(r"\b(escribe al final|añade al final|agrega al final)\b", 2.5, "fs_append"),

    # Filesystem — crear con nombre explícito
    _r(r"\b(crea|crear|genera|generar|haz|hacer)\b.{0,30}\b(archivo|fichero|carpeta|directorio)\b.{0,30}\b(llamado|con nombre|llámalo|llamada)\b", 2.5, "fs_create_named"),
    _r(r"\b(crea|crear|genera|generar)\b.{0,20}[\w\-]+\.(txt|py|json|csv|md|log|yaml|yml|toml|ini)\b", 2.5, "fs_create_named"),
    _r(r"\b(archivo|fichero)\b.{0,20}\b(llamado|con nombre|llámalo)\b", 2.0, "fs_create_named"),

    # Filesystem — crear genérico (sin nombre → irá a no_op en el prompt)
    _r(r"\b(crea|crear|genera|generar|haz|hacer)\b.{0,30}\b(archivo|fichero)\b", 1.5, "fs_create"),
    _r(r"\b(escribe|escribir)\b.{0,20}\b(archivo|fichero)\b", 1.5, "fs_create"),

    # Filesystem — leer
    _r(r"\b(lee|leer|abre|abrir|muestra|mostrar|ver|dame)\b.{0,30}\b(archivo|fichero|contenido de)\b", 2.0, "fs_read"),
    _r(r"\b(lee|leer)\b.{0,15}\b(el|un|ese|este)\b.{0,15}\b(archivo|fichero)\b", 2.0, "fs_read"),

    # Filesystem — listar
    _r(r"\b(lista|listar|muestra|mostrar)\b.{0,20}\b(archivos|ficheros|directorio|carpeta|contenido de)\b", 2.0, "fs_list"),
    _r(r"\b(qué hay en|qué contiene)\b.{0,30}\b(carpeta|directorio)\b", 1.5, "fs_list"),

    # Comandos del sistema
    _r(r"\b(ejecuta|ejecutar|corre|correr|lanza|lanzar)\b.{0,20}\b(comando|script|programa)\b", 2.0, "cmd"),

    # Información del sistema
    _r(r"\b(info(rmación)?|estado|status)\b.{0,20}\b(sistema|cpu|ram|memoria|disco)\b", 1.5, "sysinfo"),
    _r(r"\bcuánta (ram|memoria|cpu)\b", 1.5, "sysinfo"),

    # Abrir aplicaciones
    _r(r"\b(abre|abrir|lanza|lanzar|inicia|iniciar)\b.{0,20}\b(aplicación|programa|app|navegador|firefox|chrome|vscode|notepad|terminal)\b", 2.0, "open_app"),

    # Paths y extensiones explícitas en la frase
    _r(r"[\w\-]+\.(txt|py|json|csv|md|log|yaml|yml|toml|ini)\b", 1.2, "extension"),
    _r(r"[/\\][\w/\\.\-]+\.\w{1,6}", 1.0, "path"),
]

# ---------------------------------------------------------------------------
# Reglas negativas — penalizan (el usuario habla SOBRE cosas, no pide acción)
# ---------------------------------------------------------------------------
_CHAT_RULES: list[_Rule] = [
    # Escritura creativa — "escribe una carta/email/poema" → chat
    _r(r"\b(escribe|escribir|redacta|redactar)\b.{0,40}\b(carta|email|correo|poema|texto|artículo|ensayo|historia|cuento|mensaje|resumen|canción)\b", -2.5, "creative"),

    # Preguntas teóricas
    _r(r"\b(qué es|qué son|cómo funciona|explica|explícame|dime qué)\b", -1.2, "theory"),

    # Saludos y conversación normal
    _r(r"^(hola|buenos? días|buenas? tardes|buenas? noches|hey|hi|qué tal|cómo estás|gracias|ok|vale|genial|perfecto|de acuerdo)\b", -2.5, "greeting"),

    # Preguntas generales que no implican acción
    _r(r"\b(cuándo|dónde|por qué|para qué|quién)\b.{0,40}\?", -0.8, "question"),

    # "Puedes hacer X" sin nombre de archivo → probablemente solo pregunta
    _r(r"^(puedes|podrías|puedo)\b.{0,30}\?$", -0.5, "question_can"),
]

# Umbral para considerar que necesita herramienta
_THRESHOLD = 1.5


class IntentRouter:

    def detect(self, message: str) -> Intent:
        return self.detect_with_detail(message)["intent"]

    def detect_with_detail(self, message: str) -> dict:
        score = 0.0
        fired: list[str] = []

        for rule in _TOOL_RULES:
            if rule.pattern.search(message):
                score += rule.weight
                fired.append(f"+{rule.weight} [{rule.category}]")

        for rule in _CHAT_RULES:
            if rule.pattern.search(message):
                score += rule.weight
                fired.append(f"{rule.weight} [{rule.category}]")

        return {
            "intent": "tool" if score >= _THRESHOLD else "chat",
            "score": round(score, 2),
            "threshold": _THRESHOLD,
            "fired_rules": fired,
        }