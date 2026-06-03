import asyncio
import pytest
from app.core.event_bus import EventBus

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    """Verifica que un mensaje publicado llegue al suscriptor correctamente."""
    bus = EventBus()
    received_data = []

    async def mock_callback(data):
        received_data.append(data)

    bus.subscribe("test.event", mock_callback)
    await bus.start()
    
    payload = {"message": "hola Alfonso"}
    await bus.publish("test.event", payload)
    
    # Pequeña espera para que el loop interno procese la cola
    await asyncio.sleep(0.1)
    
    assert len(received_data) == 1
    assert received_data[0] == payload
    await bus.stop()

@pytest.mark.asyncio
async def test_event_bus_error_isolation():
    """Asegura que un fallo en un suscriptor no rompa el procesamiento de otros."""
    bus = EventBus()
    results = []

    async def faulty_callback(data):
        raise Exception("Explosión controlada")

    async def healthy_callback(data):
        results.append(data)

    bus.subscribe("critical.event", faulty_callback)
    bus.subscribe("critical.event", healthy_callback)
    
    await bus.start()
    await bus.publish("critical.event", {"status": "ok"})
    
    await asyncio.sleep(0.1)
    
    # El bus debe seguir vivo y el segundo callback debe haber ejecutado
    assert len(results) == 1
    assert bus._running is True
    await bus.stop()

@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    """Valida que un suscriptor deje de recibir eventos."""
    bus = EventBus()
    count = 0
    async def counter_cb(data): nonlocal count; count += 1
    
    bus.subscribe("event", counter_cb)
    bus.unsubscribe("event", counter_cb)
    
    await bus.start()
    await bus.publish("event", {})
    await asyncio.sleep(0.1)
    
    assert count == 0
    await bus.stop()