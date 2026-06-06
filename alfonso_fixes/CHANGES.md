# Alfonso — Cambios Fase 3

## Bugs corregidos

### 1. Race condition en ChatAgent (chat timeout 30s)
**Archivo:** `app/agents/chat_agent.py`

El ChatAgent hacía timeout porque el LLM podía no estar inyectado cuando llegaba el
primer evento. El fix acepta `_llm` directamente desde el payload del evento como
fallback, igual que ya hacía el PlannerOrchestrator al pasar `_llm` en el event_data.

### 2. `open_application` no encontraba `firefox` ni el explorador de archivos
**Archivo:** `app/tools/system_tools.py`

En WSL, muchas apps gráficas no están en el PATH estándar. Añadidos:
- Fallback automático a `xdg-open` cuando el binario no existe.
- `_find_file_manager()`: detecta `nautilus`, `nemo`, `thunar`, `dolphin`, etc.
- `_APP_ALIASES`: mapea strings como `"internet"` → `xdg-open https://...`
- Nueva tool `get_current_datetime()` para devolver la hora real del sistema.

### 3. IntentRouter no detectaba "explorador de archivos" ni URLs
**Archivo:** `app/core/intent_router.py`

`"buenos dias, abre exploraddor de archivos"` daba score 0.00 (chat).
Añadidas reglas para:
- Explorador de archivos con typos (`explorad*`, `gestor de archivos`, `nautilus`, etc.)
- Acciones de navegador web (`navega a`, `abre la web`, URLs explícitas)
- Preguntas de fecha/hora actual (intent `datetime_tool`)

### 4. El LLM inventaba fechas incorrectas
**Archivos:** `app/core/llm_client.py`, `app/prompts/chat_system.txt`, `app/core/planner_orchestrator.py`

El modelo Qwen 2.5:1.5b respondía "hoy es domingo", "hoy es viernes", etc. con
fechas incorrectas. Tres capas de fix:

1. `llm_client.py`: inyecta `{current_date}` real en el prompt del sistema en cada llamada.
2. `chat_system.txt`: incluye instrucción explícita de usar la fecha inyectada.
3. `planner_orchestrator.py`: si el IntentRouter detecta `datetime_tool`, saltamos el LLM
   completamente y despachamos directamente a `system.datetime` → `get_current_datetime`.

### 5. `audio_orchestrator.py` importaba clase inexistente
**Archivo:** `audio_orchestrator.py`

Importaba `Orchestrator` (Fase 1) que ya no existe. Corregido a `PlannerOrchestrator`.

---

## Nuevas features Fase 3

### Tool `get_current_datetime`
Devuelve fecha, hora, día de la semana y formato humano en español.
Registrada en `TOOLS` de `system_tools.py`, mapeada como `system.datetime` en
`TaskPlanner` y `SystemAgent`.

### IntentRouter: reglas de navegador y fecha
Nuevas categorías: `browser_navigate`, `browser_open`, `browser_search`,
`url_explicit`, `datetime_tool`, `open_filemanager`, `open_filemanager_short`.

### Prompt del sistema con fecha real
`chat_system.txt` recibe `{current_date}` actualizado en cada request.
`tool_system.txt` tiene reglas explícitas para `get_current_datetime`.

---

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `app/agents/chat_agent.py` | Fix race condition LLM |
| `app/agents/system_agent.py` | Añade `system.datetime` |
| `app/agents/registry.py` | Comentario de system.datetime |
| `app/agents/task_planner.py` | Mapea `get_current_datetime` → `system.datetime` |
| `app/core/intent_router.py` | +8 reglas (explorador, browser, datetime) |
| `app/core/llm_client.py` | Inyección de `{current_date}` |
| `app/core/planner_orchestrator.py` | Atajo datetime, corrección alucinaciones ampliada |
| `app/tools/system_tools.py` | xdg-open fallback, file manager, `get_current_datetime` |
| `app/prompts/tool_system.txt` | Reglas get_current_datetime, browser, file manager |
| `app/prompts/chat_system.txt` | Fecha real inyectada, awareness de tools |
| `audio_orchestrator.py` | Fix import PlannerOrchestrator |

---

## Cómo aplicar los cambios

Copia cada archivo desde esta carpeta a la ruta correspondiente en tu proyecto:

```bash
# Desde la raíz del proyecto Alfonso/
cp fixes/app/agents/chat_agent.py         app/agents/chat_agent.py
cp fixes/app/agents/system_agent.py       app/agents/system_agent.py
cp fixes/app/agents/registry.py           app/agents/registry.py
cp fixes/app/agents/task_planner.py       app/agents/task_planner.py
cp fixes/app/core/intent_router.py        app/core/intent_router.py
cp fixes/app/core/llm_client.py           app/core/llm_client.py
cp fixes/app/core/planner_orchestrator.py app/core/planner_orchestrator.py
cp fixes/app/tools/system_tools.py        app/tools/system_tools.py
cp fixes/app/prompts/tool_system.txt      app/prompts/tool_system.txt
cp fixes/app/prompts/chat_system.txt      app/prompts/chat_system.txt
cp fixes/audio_orchestrator.py            audio_orchestrator.py
```

Reinicia el servidor:
```bash
uvicorn app.main:app --reload
```

---

## Próximos pasos — completar Fase 3

- [ ] Verificar que Playwright está instalado: `playwright install chromium`
- [ ] Test del `BrowserAgent` en WSL con `ALFONSO_HEADLESS=false`
- [ ] Verificar PyAutoGUI en WSL (requiere display: `export DISPLAY=:0`)
- [ ] Añadir endpoint `/browser/search` en `app/api/routes.py` para uso directo
- [ ] Fase 4: ChromaDB para memoria vectorial semántica
