# Roadmap Estratégico: Alfonso Distribuido y Multi-Cliente

Este roadmap define las fases de desarrollo necesarias para transformar a Alfonso en un **sistema operativo agentico distribuido**, capaz de actuar como un servidor central de red local que coordina múltiples clientes de escritorio (PC, portátiles) y dispositivos inteligentes (domótica), superando la naturaleza monolítica de competidores como Open Interpreter.

---

## ── FASE A: Arquitectura de Red y Bridge Multi-Cliente (Duración: 5 semanas) ──
El objetivo es permitir que el servidor Alfonso (FastAPI en Linux/Docker/WSL) acepte, registre y diferencie múltiples clientes de escritorio en la red local de forma concurrente.

*   **A.1. Registro y Handshake con Metadatos:** Rediseñar `alfonso_bridge.py` para realizar un apretón de manos (*handshake*) donde cada cliente se identifique con un `client_id` único, nombre de host (`hostname`), sistema operativo, usuario activo e IP local.
*   **A.2. Tabla de Enrutamiento en Tiempo Real:** Implementar una tabla de conexiones activas en el bridge para mapear de manera unívoca peticiones específicas de herramientas a los canales WebSocket correspondientes.
*   **A.3. Adaptación de Herramientas de Sistema:** Modificar la firma de las herramientas en `system_tools.py` y `browser_tools.py` para que acepten un parámetro `client_id` obligatorio, permitiendo ejecutar acciones (clics, capturas, abrir apps) exclusivamente en la máquina que originó la consulta.

---

## ── FASE B: Seguridad, Control de Acceso (RBAC) y Privacidad (Duración: 5 semanas) ──
El objetivo es blindar el servidor frente a accesos no autorizados y definir qué puede hacer cada cliente en la red.

*   **B.1. Autenticación de Clientes por Token:** Implementar un sistema de tokens de seguridad específicos para cada cliente autorizado, evitando conexiones no deseadas en la red local.
*   **B.2. Control de Acceso Basado en Roles (RBAC):** Definir perfiles de permisos:
    *   *Administrador:* Acceso a herramientas del servidor (Gmail, bases de datos globales, configuración) y herramientas locales de su propia máquina.
    *   *Invitado / Limitado:* Ejecución exclusiva de herramientas del sistema en su propio ordenador, sin acceso a la información personal ni integraciones externas del servidor central.
*   **B.3. Aislamiento de Memoria por Sesión/Máquina:** Adaptar la base de datos de memoria conversacional para que recupere el contexto y recuerdos semánticos (ChromaDB/SQLite) utilizando el identificador `(user_id, client_id)` de la máquina emisora.

---

## ── FASE C: Cognición Sensible al Contexto de Máquina (Duración: 4 semanas) ──
El objetivo es que el LLM del servidor sea consciente de a quién y a qué máquina está respondiendo en cada mensaje.

*   **C.1. Inyección Dinámica de Prompt de Máquina:** Configurar el orquestador (`PlannerOrchestrator`) para inyectar en el prompt del sistema las características de la máquina cliente activa antes de procesar cada turno de chat.
*   **C.2. Function Calling Nativo con Modelos Locales:** Implementar modelos de 7B u 8B optimizados para llamadas a funciones que puedan estructurar las acciones distribuidas sin depender de heurísticas o palabras clave cableadas en el código.

---

## ── FASE D: Clientes Ligeros Nativos (Tauri) y Audio Distribuido (Duración: 6 semanas) ──
El objetivo es proveer a los ordenadores de la red de un cliente de escritorio liviano, visualmente premium y eficiente en el uso de recursos.

*   **D.1. Cliente Universal Tauri (System Tray):** Desarrollar un cliente ligero con Tauri (Rust + HTML5) de bajo consumo de recursos (<20MB RAM) instalable en Windows, macOS y Linux.
*   **D.2. Streaming de Voz Bidireccional Localizado:**
    *   *STT local en cliente:* Integrar transcripción en tiempo real con `Whisper.cpp` en el cliente para enviar únicamente texto ligero al servidor.
    *   *TTS en cliente:* Enviar el texto de respuesta del servidor de vuelta al cliente para que este lo sintetice y reproduzca localmente usando las APIs nativas del SO o `Piper TTS` cuantizado.

---

## ── FASE E: Integración Domótica (IoT) y Proactividad (Duración: 6 semanas) ──
El objetivo es conectar el servidor de Alfonso de forma permanente a la infraestructura de automatización del hogar.

*   **E.1. Agente IoT Integrado:** Añadir un adaptador de red en el Core para conectarse a plataformas como **Home Assistant** (vía WebSockets/REST API) o brokers **MQTT** locales.
*   **E.2. Daemon de Monitoreo Proactivo:** Diseñar un loop de fondo en el servidor central que escuche eventos de domótica (sensores de presencia, temperatura, estado de electrodomésticos) o llegada de correos importantes.
*   **E.3. Notificaciones y Sugerencias Inteligentes:** Emitir alertas proactivas a los clientes de escritorio activos sugiriendo flujos de trabajo basados en el estado físico de la red o la casa (ej. *"He detectado que la lavadora ha terminado y tu calendario está libre los próximos 10 minutos. ¿Deseas un recordatorio en tu móvil?"*).
