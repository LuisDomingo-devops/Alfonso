import asyncio
from app.core.event_bus import EventBus

async def test():
    bus = EventBus()

    resultados = []

    async def on_file_created(data):
        resultados.append(data)

    bus.subscribe("file.created", on_file_created)
    await bus.start()

    await bus.publish("file.created", {"path": "notas.txt", "status": "ok"})
    await asyncio.sleep(0.2)  # dar tiempo al procesador

    assert len(resultados) == 1
    assert resultados[0]["path"] == "notas.txt"

    await bus.stop()
    print("Test OK")

asyncio.run(test())