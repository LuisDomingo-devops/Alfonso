"""
TIMER — Medición precisa de latencias y tiempos de ejecución.

¿QUÉ HACE?
Expone un administrador de contexto para medir la duración de ejecuciones de código.

¿CUÁNDO LO HACE?
Al registrar latencias de endpoints REST o llamadas a herramientas.

¿CÓMO LO HACE?
Usando `time.perf_counter()` en los métodos especiales `__enter__` y `__exit__` de Python.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py (mide la latencia de /chat y herramientas de Playwright)
"""

import time


class Timer:

    def __init__(self):
        self.start = None
        self.end = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end = time.perf_counter()

    @property
    def elapsed(self):
        return round(self.end - self.start, 3)