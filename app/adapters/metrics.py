"""
METRICS — Recolección de métricas internas del servidor.

¿QUÉ HACE?
Realiza un seguimiento del conteo de solicitudes HTTP, incidencias de errores y latencias de respuesta del sistema.

¿CUÁNDO LO HACE?
En cada petición HTTP interceptada por el middleware de la aplicación o al ocurrir una excepción controlada.

¿CÓMO LO HACE?
Incrementando variables globales seguras en memoria y devolviendo un snapshot agregado en formato JSON.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/main.py (actualiza las métricas a través de middlewares y manejadores de errores)
- app/api/routes.py (expone el endpoint GET `/metrics` para monitorear el rendimiento)
"""

from collections import defaultdict
from statistics import mean

_metrics = defaultdict(int)
_latency_ms = []


def increment_http_requests(count: int = 1):
    _metrics["http_requests"] += count


def increment_http_errors(count: int = 1):
    _metrics["http_errors"] += count


def increment_websocket_connections(count: int = 1):
    _metrics["websocket_connections"] += count


def increment_websocket_messages(count: int = 1):
    _metrics["websocket_messages"] += count


def record_http_latency(seconds: float):
    _metrics["http_responses"] += 1
    _latency_ms.append(seconds * 1000)


def snapshot() -> dict:
    avg_latency = round(mean(_latency_ms), 3) if _latency_ms else 0.0
    return {
        "http_requests": _metrics["http_requests"],
        "http_errors": _metrics["http_errors"],
        "http_responses": _metrics["http_responses"],
        "average_http_latency_ms": avg_latency,
        "websocket_connections": _metrics["websocket_connections"],
        "websocket_messages": _metrics["websocket_messages"],
    }
