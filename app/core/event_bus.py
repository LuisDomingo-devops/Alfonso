import asyncio
import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger("event_bus")


class EventBus:

    def __init__(self):
        # No tocar el loop aquí — se resuelve en tiempo async
        self._queues: Dict[str, asyncio.Queue] = {}
        self._subscribers: Dict[str, List[Callable]] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._new_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Arranca el procesador de eventos. Llamar desde lifespan de FastAPI."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_events())
        logger.info("EventBus iniciado")

    async def stop(self) -> None:
        """Para el bus limpiamente."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EventBus detenido")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def publish(self, event_type: str, data: Any) -> None:
        """Publica un evento. Crea la cola si no existe."""
        if event_type not in self._queues:
            self._queues[event_type] = asyncio.Queue()
        await self._queues[event_type].put(data)
        self._new_event.set()
        logger.debug("Evento publicado: %s", event_type)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Registra un callback para un tipo de evento.
        Síncrono a propósito: se llama al arrancar, no durante el loop.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.info("Suscriptor registrado: %s → %s", event_type, callback.__name__)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]

    # ------------------------------------------------------------------
    # Loop interno
    # ------------------------------------------------------------------

    async def _process_events(self) -> None:
        """
        Procesa eventos de todas las colas.
        Usa una copia de las keys para evitar RuntimeError si se añade
        una cola nueva durante la iteración.
        """
        while self._running:
            # Snapshot de las colas actuales para iterar de forma segura
            current_queues = list(self._queues.items())

            for event_type, queue in current_queues:
                subscribers = self._subscribers.get(event_type, [])
                if not subscribers:
                    continue

                # Drena todos los eventos pendientes en esta cola
                while not queue.empty():
                    try:
                        data = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    for callback in subscribers:
                        asyncio.create_task(
                            self._safe_call(callback, event_type, data)
                        )

            await asyncio.sleep(0.05)

    @staticmethod
    async def _safe_call(callback: Callable, event_type: str, data: Any) -> None:
        """Envuelve el callback para que un fallo no rompa el bus."""
        try:
            await callback(data)
        except Exception:
            logger.exception(
                "Error en callback '%s' para evento '%s'",
                callback.__name__,
                event_type,
            )