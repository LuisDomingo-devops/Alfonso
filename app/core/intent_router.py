"""
IntentRouter — Fase 3.

Mejoras respecto a Fase 2:
- Añadidos patrones para 'explorador de archivos', 'nautilus', 'nemo', 'thunar'.
- Añadidos patrones para acciones de navegador (navega a, abre la web, busca en).
- Añadida regla para consultas de fecha/hora actuales via run_command.
- Aumentado peso de 'explorador de archivos' para superar la penalización de saludos.
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

    # ── Filesystem — DELETE ──────────────────────────────────────────
    _r(r"\b(elimina|eliminar|borra|borrar|suprime|suprimir|remove|delete|quita|quitar)\b.{0,40}\b(archivo|fichero|\.txt|\.py|\.json|\.csv|\.md|\.log|\.yaml|\.yml|\.toml|\.ini)\b", 3.5, "fs_delete"),
    _r(r"\b(elimina|eliminar|borra|borrar|suprime|suprimir|remove|delete)\b.{0,20}[\w\-]+\.(txt|py|json|csv|md|log|yaml|yml|toml|ini)\b", 3.0, "fs_delete_ext"),
    _r(r"\b(borra|elimina|delete|remove)\b.{0,30}\b(el|ese|este|un|la)\b.{0,15}\b(archivo|fichero)\b", 2.5, "fs_delete_generic"),

    # ── Filesystem — append ──────────────────────────────────────────
    _r(r"\b(añade|añadir|agrega|agregar|append)\b.{0,50}\b(archivo|fichero|al archivo|a ese archivo|al final|\.txt|\.py|\.json|\.csv|\.md)\b", 3.0, "fs_append"),
    _r(r"\b(escribe al final|añade al final|agrega al final)\b", 2.5, "fs_append"),

    # ── Filesystem — crear con nombre explícito ──────────────────────
    _r(r"\b(crea|crear|genera|generar|haz|hacer)\b.{0,30}\b(archivo|fichero|carpeta|directorio)\b.{0,30}\b(llamado|con nombre|llámalo|llamada)\b", 2.5, "fs_create_named"),
    _r(r"\b(crea|crear|genera|generar)\b.{0,20}[\w\-]+\.(txt|py|json|csv|md|log|yaml|yml|toml|ini)\b", 2.5, "fs_create_named"),
    _r(r"\b(archivo|fichero)\b.{0,20}\b(llamado|con nombre|llámalo)\b", 2.0, "fs_create_named"),

    # ── Filesystem — crear genérico ──────────────────────────────────
    _r(r"\b(crea|crear|genera|generar|haz|hacer)\b.{0,30}\b(archivo|fichero)\b", 1.5, "fs_create"),
    _r(r"\b(escribe|escribir)\b.{0,20}\b(archivo|fichero)\b", 1.5, "fs_create"),

    # ── Filesystem — leer ────────────────────────────────────────────
    _r(r"\b(lee|leer|abre|abrir|muestra|mostrar|ver|dame)\b.{0,30}\b(archivo|fichero|contenido de)\b", 2.0, "fs_read"),
    _r(r"\b(lee|leer)\b.{0,15}\b(el|un|ese|este)\b.{0,15}\b(archivo|fichero)\b", 2.0, "fs_read"),

    # ── Filesystem — listar ──────────────────────────────────────────
    _r(r"\b(lista|listar|muestra|mostrar)\b.{0,20}\b(archivos|ficheros|directorio|carpeta|contenido de)\b", 2.0, "fs_list"),
    _r(r"\b(qué hay en|qué contiene)\b.{0,30}\b(carpeta|directorio)\b", 1.5, "fs_list"),

    # ── Comandos del sistema ─────────────────────────────────────────
    _r(r"\b(ejecuta|ejecutar|corre|correr|lanza|lanzar)\b.{0,20}\b(comando|script|programa)\b", 2.0, "cmd"),

    # ── Información del sistema ──────────────────────────────────────
    _r(r"\b(info(rmación)?|estado|status)\b.{0,20}\b(sistema|cpu|ram|memoria|disco)\b", 1.5, "sysinfo"),
    _r(r"\bcuánta (ram|memoria|cpu)\b", 1.5, "sysinfo"),

    # ── Abrir aplicaciones — genéricas ───────────────────────────────
    _r(r"\b(abre|abrir|lanza|lanzar|inicia|iniciar)\b.{0,20}\b(aplicación|programa|app|navegador|firefox|chrome|chromium|vscode|notepad|terminal|konsole|gedit|kate)\b", 2.0, "open_app"),

    # ── Cerrar aplicaciones ────────────────────────────────────────────
    _r(r"\b(cierra|cerrar|termina|terminar|mata|matar|quit|exit)\b.{0,30}\b(aplicación|programa|app|navegador|firefox|chrome|vscode|notepad|terminal|explorador de archivos|nautilus)\b", 2.5, "close_application"),
    _r(r"^(cierra|cerrar|mata|matar)\s+\w+$", 2.0, "close_app_simple"),

    # ── Abrir explorador de archivos (FIX) ───────────────────────────
    # Se añaden: explorador (con typos), gestor de archivos, nautilus, nemo, thunar, dolphin
    _r(r"\b(abre|abrir|lanza|inicia)\b.{0,25}\b(explorad?or de archivos|gestor de archivos|file manager|nautilus|nemo|thunar|dolphin|explorer|caja)\b", 3.0, "open_filemanager"),
    _r(r"\b(abre|abrir)\b.{0,15}\b(explorad?or|explorador|explorad?or)\b", 2.5, "open_filemanager_short"),

    # ── Navegador web — acciones (Fase 3) ────────────────────────────
    _r(r"\b(navega|navegar|ve|ir)\b.{0,20}\b(a la web|a la página|a la url|al sitio|a https?://|a www\.)\b", 2.5, "browser_navigate"),
    _r(r"\b(abre|abrir)\b.{0,15}\b(la web|la página|internet|el navegador|una url|el sitio|https?://|www\.)\b", 2.0, "browser_open"),
    _r(r"\b(busca|buscar|googlea|googleas?)\b.{0,30}\b(en internet|en google|en la web|online|en línea)\b", 2.5, "browser_search"),
    _r(r"https?://[\w\-\.]+\.\w{2,}", 2.0, "url_explicit"),

    # ── Fecha y hora actuales via sistema (FIX) ───────────────────────
    # El LLM no conoce la fecha real; estas preguntas deben ir al sistema
    _r(r"\b(qué hora|que hora|la hora actual|qué son las|son las)\b", 2.0, "datetime_tool"),
    _r(r"\b(qué día|que dia|hoy es|día de hoy|fecha actual|fecha de hoy)\b.{0,20}\?", 2.0, "datetime_tool"),

    # ── Mail (Fase 3 — patrones avanzados) ───────────────────────────
    _r(r"\b(responde|contesta|redacta respuesta)\b.{0,30}\b(mail|correo|reclamación|abogado)\b", 3.0, "mail_reply"),
    _r(r"\b(aplica|inscríbete|postula)\b.{0,30}\b(oferta|trabajo|empleo|infojobs)\b", 3.5, "mail_apply"),

    # ── Paths y extensiones explícitas ───────────────────────────────
    _r(r"[\w\-]+\.(txt|py|json|csv|md|log|yaml|yml|toml|ini)\b", 1.2, "extension"),
    _r(r"[/\\][\w/\\.\-]+\.\w{1,6}", 1.0, "path"),
]

# ---------------------------------------------------------------------------
# Reglas negativas — penalizan el score de tool
# ---------------------------------------------------------------------------
_CHAT_RULES: list[_Rule] = [
    # Escritura creativa
    _r(r"\b(escribe|escribir|redacta|redactar)\b.{0,40}\b(carta|email|correo|poema|texto|artículo|ensayo|historia|cuento|mensaje|resumen|canción)\b", -2.5, "creative"),

    # Preguntas teóricas
    _r(r"\b(qué es|qué son|cómo funciona|explica|explícame|dime qué)\b", -1.2, "theory"),

    # Saludos / conversación
    _r(r"^(hola|buenos? días|buenas? tardes|buenas? noches|hey|hi|qué tal|cómo estás|gracias|ok|vale|genial|perfecto|de acuerdo)\b", -2.5, "greeting"),

    # Preguntas generales
    _r(r"\b(cuándo|dónde|por qué|para qué|quién)\b.{0,40}\?", -0.8, "question"),

    # "¿Puedes hacer X?" sin nombre de archivo
    _r(r"^(puedes|podrías|puedo)\b.{0,30}\?$", -0.5, "question_can"),
]

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
