"""
IntentRouter — Fase 1 completa.

Detecta si el mensaje del usuario requiere una herramienta o es chat.
Usa un sistema de scoring por categorías en lugar de keywords simples,
evitando falsos positivos como "escríbeme una carta" → tool_mode.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Literal

Intent = Literal["chat", "tool"]


@dataclass
class _Rule:
    """Un patrón de detección con su peso."""
    pattern: re.Pattern
    weight: float
    category: str


def _r(pattern: str, weight: float, category: str) -> _Rule:
    return _Rule(re.compile(pattern, re.IGNORECASE), weight, category)


# ---------------------------------------------------------------------------
# Reglas positivas (indican que se necesita una tool)
# ---------------------------------------------------------------------------
_TOOL_RULES: list[_Rule] = [
    # Filesystem — crear
    _r(r"\b(crea|crear|genera|generar|escribe|escribir|haz|hacer)\b.{0,30}\b(archivo|fichero|carpeta|directorio|\.txt|\.py|\.json|\.csv|\.md)\b", 2.0, "fs_create"),
    _r(r"\b(archivo|fichero)\b.{0,20}\b(llamado|con nombre|llámalo)\b", 1.5, "fs_create"),
    # Filesystem — leer
    _r(r"\b(lee|leer|abre|abrir|muestra|mostrar|ver|dame)\b.{0,30}\b(archivo|fichero|contenido)\b", 2.0, "fs_read"),
    _r(r"\b(lee|leer)\b.{0,15}\b(el|un|ese|este)\b.{0,15}\b(archivo|fichero)\b", 1.8, "fs_read"),
    # Filesystem — listar/directorio
    _r(r"\b(lista|listar|muestra|mostrar)\b.{0,20}\b(archivos|ficheros|directorio|carpeta|contenido de)\b", 2.0, "fs_list"),
    _r(r"\b(qué hay en|qué contiene|contenido de)\b.{0,30}\b(carpeta|directorio)\b", 1.5, "fs_list"),
    # Filesystem — añadir
    _r(r"\b(añade|añadir|agrega|agregar|append)\b.{0,30}\b(archivo|fichero|al archivo|a ese archivo)\b", 2.0, "fs_append"),
    # Comandos del sistema
    _r(r"\b(ejecuta|ejecutar|corre|correr|lanza|lanzar)\b.{0,20}\b(comando|script|programa)\b", 2.0, "cmd"),
    _r(r"\b(run|exec)\b.{0,20}\b(command|script)\b", 1.5, "cmd"),
    # Información del sistema
    _r(r"\b(info|información|estado|status)\b.{0,20}\b(sistema|cpu|ram|memoria|disco)\b", 1.5, "sysinfo"),
    _r(r"\bcuánta (ram|memoria|cpu)\b", 1.5, "sysinfo"),
    # Abrir aplicaciones
    _r(r"\b(abre|abrir|lanza|lanzar|inicia|iniciar|arranca)\b.{0,20}\b(la aplicación|el programa|la app|el navegador|firefox|chrome|vscode|notepad)\b", 1.8, "open_app"),
    # Paths explícitos
    _r(r"[/\\][\w/\\.\-]+\.\w{1,6}", 1.2, "path"),
    _r(r"\.\w{2,5}\b", 0.8, "extension"),
]

# ---------------------------------------------------------------------------
# Reglas negativas (penalizan — el usuario habla SOBRE archivos, no pide acción)
# ---------------------------------------------------------------------------
_CHAT_RULES: list[_Rule] = [
    # Preguntas teóricas
    _r(r"\b(qué es|qué son|cómo funciona|explica|explícame|dime qué)\b", -1.2, "theory"),
    # Escritura creativa / textos
    _r(r"\b(escribe|escribir|redacta|redactar)\b.{0,30}\b(carta|email|correo|poema|texto|artículo|ensayo|historia|cuento|mensaje|resumen)\b", -2.0, "creative"),
    # Conversación normal
    _r(r"^(hola|buenos días|buenas tardes|buenas noches|hey|hi|qué tal|cómo estás|gracias|ok|vale|genial|perfecto)\b", -2.0, "greeting"),
    # Preguntas generales
    _r(r"\b(cuánto|cuándo|dónde|por qué|para qué|quién)\b.{0,40}\?", -0.8, "question"),
]

# Umbral de score para considerar que es una tool
_THRESHOLD = 1.5


class IntentRouter:
    """
    Calcula un score ponderado para decidir si el mensaje necesita
    una herramienta o es una conversación normal.
    """

    def detect(self, message: str) -> Intent:
        score = 0.0

        for rule in _TOOL_RULES:
            if rule.pattern.search(message):
                score += rule.weight

        for rule in _CHAT_RULES:
            if rule.pattern.search(message):
                score += rule.weight  # peso negativo

        return "tool" if score >= _THRESHOLD else "chat"

    def detect_with_detail(self, message: str) -> dict:
        """Para debugging: devuelve score y qué reglas dispararon."""
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