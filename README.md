---
title: Alfonso
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

Arquitehcture:

                ┌─────────────────────┐
                │   FASTAPI CORE      │
                │  (ligero, async)    │
                └─────────┬───────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │ ORCHESTRATOR LIGERO │
                │  (no persistente)   │
                └─────────┬───────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ TOOL ENGINE  │  │ MEMORY LITE  │  │ EVENT QUEUE  │
│ stateless    │  │ SQLite only  │  │ asyncio only │
└──────────────┘  └──────────────┘  └──────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │  LLM CLIENT LAYER   │
                │  (Ollama on-demand) │
                └─────────────────────┘

Logs:
- Archivos generados en la carpeta `logs/`.
- Los principales archivos son `app.log`, `orchestrator.log`, `llm.log`, `errors.log`, y `tool_registry.log`.
- Cada request recibe un `request_id` UUID que aparece en todos los mensajes para seguir el flujo completo.

Audio:
- `POST /audio/tts` → convierte texto a voz usando backend `edge-tts` con fallback a `pyttsx3`
- `POST /audio/stt` → convierte voz a texto usando `whisper` con fallback a `speech_recognition`
- `POST /audio/wakeword` → detecta la palabra de activación desde el micrófono usando STT continuo

Endpoints nuevos:
- `GET /health` → estado de la aplicación y ruta de logs
- `GET /metrics` → métricas básicas de requests y websocket
- `GET /ws` → websocket realtime para pruebas de eco
