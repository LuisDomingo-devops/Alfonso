import re
from pathlib import Path
from dataclasses import dataclass
from collections import Counter
from datetime import datetime

@dataclass
class LogEvent:
    timestamp: datetime
    level: str          # INFO, WARNING, ERROR, DEBUG
    logger: str         # llm, orchestrator, tools, etc.
    request_id: str
    message: str
    traceback: str | None = None

LOG_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+\|\s+(\w+)\s+\|\s+(\w+)\s+\|\s+\[([^\]]+)\]\s+(.*)"
)

def parse_log_file(path: Path) -> list[LogEvent]:
    events = []
    lines = path.read_text(encoding="utf-8").splitlines()
    current_event = None
    traceback_lines = []

    for line in lines:
        m = LOG_PATTERN.match(line)
        if m:
            if current_event:
                current_event.traceback = "\n".join(traceback_lines) if traceback_lines else None
                events.append(current_event)
                traceback_lines = []
            ts_str, level, logger, req_id, message = m.groups()
            current_event = LogEvent(
                timestamp=datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f"),
                level=level,
                logger=logger,
                request_id=req_id,
                message=message,
            )
        elif current_event:
            traceback_lines.append(line.strip())

    if current_event:
        current_event.traceback = "\n".join(traceback_lines) if traceback_lines else None
        events.append(current_event)

    return events

def summarize_for_llm(events: list[LogEvent], max_errors: int = 20) -> str:
    """
    Genera un resumen compacto para no saturar el contexto del LLM.
    """
    errors = [e for e in events if e.level == "ERROR"]
    warnings = [e for e in events if e.level == "WARNING"]
    
    # Agrupar errores por tipo (el mensaje sin la parte variable)
    error_patterns = Counter()
    error_examples = {}
    for e in errors:
        # Normalizar: quitar UUIDs, rutas, números
        key = re.sub(r"[a-f0-9-]{36}", "<UUID>", e.message)
        key = re.sub(r"/[^\s]+", "<PATH>", key)
        key = re.sub(r"\d+", "<N>", key)
        error_patterns[key] += 1
        if key not in error_examples:
            error_examples[key] = e

    summary_lines = [
        f"Período analizado: {events[0].timestamp} → {events[-1].timestamp}",
        f"Total eventos: {len(events)} | Errores: {len(errors)} | Warnings: {len(warnings)}",
        "",
        "=== ERRORES MÁS FRECUENTES ===",
    ]
    
    for pattern, count in error_patterns.most_common(max_errors):
        example = error_examples[pattern]
        summary_lines.append(f"\n[{count}x] {example.logger}: {pattern}")
        if example.traceback:
            # Solo las últimas 3 líneas del traceback, que son las más informativas
            tb_lines = [l for l in example.traceback.splitlines() if l.strip()][-3:]
            summary_lines.append("  → " + " | ".join(tb_lines))

    summary_lines.append("\n=== WARNINGS ===")
    for w in warnings[:10]:
        summary_lines.append(f"  {w.logger}: {w.message}")

    return "\n".join(summary_lines)