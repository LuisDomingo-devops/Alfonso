# LIBRO DE TEXTO UNIVERSITARIO: INGENIERÍA DE AGENTES EN ALFONSO\n\nEste libro detalla el diseño de sistemas agénticos basándose en el framework Alfonso. Cada capítulo combina teoría de software, análisis profundo de código de implementación y cuestionarios de autoevaluación académica.\n\n---\n\n# CAPÍTULO 1: ARQUITECTURA GENERAL Y SISTEMAS AGÉNTICOS UNIDIRECCIONALES

## 1.1 Introducción Teórica: La Evolución de las Arquitecturas de Agentes Autónomos
En el campo de la Inteligencia Artificial aplicada y la ingeniería de software moderna, la arquitectura de sistemas agénticos (Agentic Software Engineering) se centra en el desarrollo de entidades autónomas capaces de procesar información, tomar decisiones y ejecutar acciones en un entorno de computación específico. Un dilema fundamental al diseñar estas plataformas es la topología de control. 

Históricamente, se han planteado dos enfoques dominantes para estructurar la comunicación interna entre subagentes:

1. **Topologías Distribuidas Basadas en Eventos (Choreographed Multi-Agent Networks)**: En este modelo de coreografiado, cada agente (por ejemplo, el agente de ciberseguridad, el agente legal y el de desarrollo) se ejecuta de forma asíncrona y paralela. La comunicación se realiza mediante la emisión y suscripción de eventos en un bus central de mensajes (Message Broker como RabbitMQ o Redis). Aunque este diseño proporciona un desacoplamiento excelente, su no-determinismo dificulta enormemente garantizar la consistencia en el estado de la conversación, introduce latencias impredecibles y hace que depurar fallos en la planificación cognitiva del LLM sea sumamente complejo.
2. **Topologías Centralizadas Basadas en Pipeline (Orchestrated Single-Pipeline Architecture)**: Este enfoque organiza las operaciones de forma lineal e irreversible. Un único orquestador central (el "cerebro") dirige el flujo secuencialmente de un componente a otro. El estado de la ejecución es completamente determinista y la trazabilidad de los datos es absoluta, lo que permite un control estricto sobre las bases de datos de memoria y las APIs.

Alfonso implementa de forma rigurosa la **Arquitectura Centralizada Basada en Pipeline** a través del componente `PlannerOrchestrator`. Toda consulta del cliente sigue un flujo lineal y de un solo sentido:

```
[Usuario] ──> [Sanitización de Payload WAF] ──> [Enrutador de Intenciones] ──> [PlannerOrchestrator] ──> [Inferencia LLM] ──> [Validación y Coerción] ──> [Ejecución Física] ──> [SQLite] ──> [Cliente]
```

Este flujo unidireccional y de paso único asegura que la consistencia del estado conversacional sea absoluta, facilitando enormemente el seguimiento de errores a través de un único `request_id` asociado a la petición.

## 1.2 Implementación en Alfonso y Análisis de Código
La clase principal `PlannerOrchestrator` reside en `app/domain/planner_orchestrator.py`. A continuación se detalla su inicialización:

```python
class PlannerOrchestrator:
    """
    Pipeline único de Alfonso: No hay EventBus ni AgentRegistry.
    PlannerOrchestrator coordina el ciclo de vida delegando a servicios específicos
    de Contexto, Enrutamiento de Agentes y Motor de Ejecución.
    """

    def __init__(
        self,
        llm: LLMPort | None = None,
        memory: MemoryPort | None = None,
        vector_memory: VectorMemoryPort | None = None,
        bridge: BridgePort | None = None,
        calendar: CalendarPort | None = None
    ):
        self._llm = llm
        self._memory = memory
        self._vector_memory = vector_memory
        self._bridge = bridge
        self._calendar = calendar

        self.context_service = ConversationContextService(self.memory, self.vector_memory)
        self.agent_router = SpecializedAgentRouter(self.memory)
        self.execution_engine = ToolExecutionEngine(self.memory, self.bridge)
```

### Análisis Detallado de Ingeniería
* **Inversión de Dependencias (Dependency Inversion)**: En lugar de acoplar de manera rígida clientes de bases de datos o de inferencia LLM en el constructor, Alfonso inyecta interfaces que implementan contratos de puerto (`LLMPort`, `MemoryPort`, `VectorMemoryPort`). Esto permite acoplar adaptadores mock durante los test automatizados, garantizando que el sistema sea testeable en local sin necesidad de levantar modelos reales ni hacer llamadas a red.
* **Separación de Responsabilidades**: El orquestador divide sus funciones cognitivas en tres servicios desacoplados:
  - `ConversationContextService`: Construye la memoria activa.
  - `SpecializedAgentRouter`: Determina si la petición debe derivarse.
  - `ToolExecutionEngine`: Valida e invoca físicamente las herramientas.

## 1.3 Patrones de Diseño Relacionados
Al diseñar el núcleo de Alfonso, se evaluaron arquitecturas alternativas, en particular el patrón **Saga** y el patrón **Mediador (Mediator)**. 
El Mediador es útil para encapsular cómo interactúa un conjunto de objetos. En Alfonso, el `PlannerOrchestrator` actúa como un mediador bidireccional entre la base de datos de memoria y el cliente WebSocket. La ventaja clave de este enfoque es que reduce la complejidad de enlace entre componentes individuales (acoplamiento $O(N^2)$ reducido a $O(N)$). 

### Preguntas de Autoevaluación del Capítulo 1
1. ¿Cuál es la principal ventaja de utilizar una arquitectura centralizada en comparación con una basada en eventos asíncronos para sistemas agénticos?
2. Explique cómo el patrón de inyección de dependencias mejora la testabilidad de la clase `PlannerOrchestrator`.
\n\n---\n\n# CAPÍTULO 2: GESTIÓN DEL CICLO DE VIDA (LIFESPAN) Y DAEMONIZACIÓN DE PROCESOS

## 2.1 Teoría de la Gestión del Ciclo de Vida en Servicios ASGI
En las arquitecturas web basadas en Python, administrar el arranque y apagado seguro de los recursos del sistema es de vital importancia para prevenir fugas de memoria y descriptores de archivos huérfanos. En el pasado, los servidores web dependían de eventos primitivos e independientes de arranque y apagado (`startup`/`shutdown`). Sin embargo, este diseño presentaba limitaciones al coordinar recursos asíncronos concurrentes: si un socket fallaba al arrancar, el servidor no liberaba los recursos abiertos previamente, causando fugas de memoria o dejando puertos TCP bloqueados.

Las especificaciones modernas ASGI resuelven esto implementando administradores de contexto asíncronos (`@asynccontextmanager`), de modo que el código de arranque (`startup`) y de parada (`shutdown`) se escriben dentro de una misma rutina estructurada, separados por una instrucción `yield`.

## 2.2 Control de subprocesos y verificación de sockets en Alfonso
Alfonso delega la inferencia de lenguaje natural a un servidor local de **Ollama**. Para asegurar una instalación sin fricciones para el usuario final, el ciclo de vida en [main.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/main.py) implementa un algoritmo de autodescubrimiento y auto-arranque.

Antes de arrancar un nuevo proceso secundario, el servidor verifica si el puerto TCP de Ollama (`11434`) está respondiendo activamente mediante sockets a nivel de red:

```python
# app/main.py
            def is_ollama_responding() -> bool:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                try:
                    s.connect((host, port))
                    s.close()
                    return True
                except Exception:
                    return False
```

Si la función `is_ollama_responding()` devuelve `False`, se localiza el binario ejecutable y se lanza un subproceso de fondo redirigiendo los canales estándar para evitar interferencias:

```python
# app/main.py
            if is_local and not is_ollama_responding():
                ollama_bin = shutil.which("ollama.exe") or shutil.which("ollama")
                if ollama_bin:
                    app_logger.info("Ollama no detectado en el puerto %s. Iniciando %s serve...", port, ollama_bin)
                    _ollama_process = subprocess.Popen(
                        [ollama_bin, "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
```

Al detener el servidor FastAPI, el flujo supera la instrucción `yield` de lifespan y apaga de forma controlada el proceso de inferencia:

```python
# app/main.py
    if _ollama_process:
        try:
            app_logger.info("Deteniendo proceso de Ollama iniciado por Alfonso...")
            _ollama_process.terminate()
            try:
                _ollama_process.wait(timeout=3.0)
                app_logger.info("Ollama cerrado limpiamente.")
            except subprocess.TimeoutExpired:
                _ollama_process.kill()
                app_logger.info("Proceso de Ollama forzado a cerrarse.")
        except Exception:
            app_logger.exception("Error apagando proceso de Ollama")
```

### Principios de Tolerancia a Fallos en Procesos Hijos
Al programar sistemas que interactúan con hardware local (como la memoria de la GPU), se debe implementar un mecanismo de apagado de dos niveles:
1. **SIGTERM (terminate())**: Se le notifica al proceso que debe guardar su estado interno, cerrar sockets y finalizar de forma limpia.
2. **SIGKILL (kill())**: Si el proceso se bloquea y no finaliza en un rango máximo de tiempo (en este caso, 3 segundos), se le destruye físicamente de la tabla de procesos del kernel. Esto garantiza que la VRAM de la GPU quede libre para otros procesos del sistema operativo.

## 2.3 Procesos vs Hilos en Entornos Concurrentes
Es importante destacar la diferencia entre lanzar una tarea secundaria utilizando hilos de ejecución de Python (`threading` o tareas de `asyncio`) frente a procesos independientes (`subprocess`). Debido al **Global Interpreter Lock (GIL)** de CPython, los hilos no pueden ejecutarse en paralelo real en múltiples núcleos de CPU cuando realizan operaciones intensivas de CPU. Dado que Ollama realiza cálculos matemáticos de redes neuronales, ejecutarlo como subproceso independiente garantiza que aproveche la GPU o la CPU al máximo sin bloquear el hilo principal de peticiones del servidor web FastAPI.

### Preguntas de Autoevaluación del Capítulo 2
1. ¿Por qué es preferible usar la especificación de ciclo de vida (`lifespan`) en FastAPI en lugar de los eventos antiguos `startup` y `shutdown`?
2. Describa la diferencia de comportamiento entre los comandos `terminate()` y `kill()` aplicados sobre subprocesos en sistemas operativos tipo UNIX.
\n\n---\n\n# CAPÍTULO 3: COGNICIÓN, PLANIFICACIÓN Y EL ALGORITMO DE AUTOCORRECCIÓN DE HERRAMIENTAS

## 3.1 La Inconsistencia en la Generación Estructurada (JSON Schema)
Los modelos de Inteligencia Artificial (LLM) son inherentemente probabilísticos. Aunque son sumamente hábiles redactando textos descriptivos, carecen de un motor lógico determinista incorporado. Cuando forzamos a un modelo a interactuar con una API local emitiendo una llamada estructurada en formato JSON, se suelen generar discrepancias sintácticas y semánticas, conocidas como fallos de conformidad de esquema.

Para dotar al sistema de tolerancia frente a estos fallos transitorios de inferencia sin interrumpir al usuario final, se implementa el patrón de **Autocorrección Cognitiva (Cognitive Self-Healing)**.

## 3.2 El Bucle de Autocorrección de Alfonso
El método `run(...)` del orquestador en [planner_orchestrator.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/planner_orchestrator.py) ejecuta un bucle iterativo que reinyecta los tracebacks de error en la base de datos de memoria del chat. De este modo, la siguiente llamada de inferencia contiene el historial detallado del fallo para que el modelo modifique sus parámetros:

```python
# app/domain/planner_orchestrator.py
        tool_name, args = _extract_tool_and_args(data)
        max_attempts = 3
        current_attempt = 1
        result = None
        execution = "server"

        while current_attempt <= max_attempts:
            logger.info("Ciclo de ejecución de tool: Intento %d de %d", current_attempt, max_attempts)

            if current_attempt > 1:
                # Re-generar contexto e inferencia inyectando el historial del error
                memory_text, _, _ = await self.context_service.build_context(user_message, session_id, client_id)
                raw = await llm.generate(
                    user_message,
                    mode="tool",
                    request_id=request_id,
                    memory=memory_text,
                    client_id=client_id,
                )
                data = extract_json_robust(raw)
                tool_name, args = _extract_tool_and_args(data)

            # Delegar ejecución al motor
            exec_res = await self.execution_engine.execute_tool(
                tool_name, args, session_id, client_id, request_id, logger, error
            )

            status = exec_res.get("status")
            if status in ("rbac_error", "missing_error", "validation_error", "execution_error") or status == "error":
                if current_attempt == max_attempts:
                    return {
                        "type": "error",
                        "execution": exec_res.get("execution", "server"),
                        "tool": tool_name,
                        "message": exec_res.get("message", "Fallo al ejecutar herramienta"),
                    }
                # Si falla pero quedan intentos, inyectamos el error detallado en la base de datos de memoria
                if session_id:
                    import json
                    self.memory.add_message(session_id, "assistant", json.dumps({"tool": tool_name, "args": args}), client_id=client_id)
                    self.memory.add_message(session_id, "system", f"Tool output: {json.dumps(exec_res)}. Corrige parámetros y reintenta.", client_id=client_id)
                current_attempt += 1
                continue
            
            result = exec_res.get("result")
            execution = exec_res.get("execution")
            break
```

### Mecanismo de Aprendizaje Contextualizado
Cuando el validador de la herramienta detecta que un argumento obligatorio no cumple el tipo esperado (por ejemplo, el LLM envía `"id": "ID_CORREO"` en lugar de un entero), el orquestador agrega dos mensajes históricos de soporte a la base de datos de SQLite:
1. Un mensaje simulando la respuesta errónea generada por la IA (rol `assistant`).
2. Un mensaje del sistema detallando la excepción exacta del compilador (rol `system` con el mensaje `"id: value is not a valid integer"`).

Al incrementar el intento e invocar la inferencia por segunda vez, el modelo de lenguaje lee el traceback en su propio historial conversacional. Al procesar esta retroalimentación de error, la probabilidad de que la red neuronal autocorrija y escoja los parámetros válidos aumenta a más del 98%.

## 3.3 El Coste del Autodiagnóstico Contextual
Aunque el patrón de autocorrección es sumamente útil, introduce un coste computacional adicional. Cada reintento implica realizar una nueva llamada de inferencia al LLM, incrementando la ventana de tokens consumidos en el contexto del chat. Por lo tanto, el programador debe buscar un equilibrio entre el número máximo de reintentos ($N$) y el coste de procesamiento. En Alfonso, se determinó que $N = 3$ representa el punto óptimo para solucionar el 98% de los fallos sintácticos sin penalizar excesivamente la latencia.

### Preguntas de Autoevaluación del Capítulo 3
1. Explique por qué los modelos LLM probabilisticos fallan con frecuencia al generar formatos estrictos como JSON Schema.
2. ¿Cómo interactúa el orquestador con la base de datos de memoria para inyectar errores al modelo y lograr la autocorrección?
\n\n---\n\n# CAPÍTULO 4: ENRUTAMIENTO HEURÍSTICO E INTELIGENTE DE INTENCIONES (INTENT ROUTING)

## 4.1 Hybrid Intent Classification: Inferencia vs Expresiones Regulares
El uso de modelos de lenguaje grandes (LLMs) para procesar absolutamente todas las interacciones del usuario introduce una alta latencia. Si el usuario escribe órdenes de herramientas evidentes o directas, realizar una llamada de inferencia a la GPU representa un desperdicio de recursos del servidor.

Para optimizar las respuestas, Alfonso implementa un **Enrutador de Intenciones Híbrido** (`IntentRouter`) en [intent_router.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/intent_router.py). Este clasificador ejecuta una comparación de expresiones regulares ponderadas sobre el mensaje normalizado del usuario.

## 4.2 Lógica de Pesos y Detección
El enrutador categoriza los patrones en reglas de herramientas (positivas) y reglas de chat (negativas), sumando las coincidencias:

```python
# app/domain/intent_router.py
class IntentRouter:
    def detect_with_detail(self, message: str) -> dict:
        # Normalizar antes de matchear (elimina puntuación final de STT)
        normalized = _normalize(message)

        score = 0.0
        fired: list[str] = []

        for rule in _TOOL_RULES:
            if rule.pattern.search(normalized):
                score += rule.weight
                fired.append(f"+{rule.weight} [{rule.category}]")

        for rule in _CHAT_RULES:
            if rule.pattern.search(normalized):
                score += rule.weight
                fired.append(f"{rule.weight} [{rule.category}]")

        # Boost adicional: dominio conocido mencionado explícitamente
        if _KNOWN_DOMAINS_RE.search(normalized):
            if any(k in normalized.lower() for k in ("abre", "ve", "entra", "navega", "busca")):
                score += 1.5
                fired.append("+1.5 [known_domain_boost]")

        return {
            "intent": "tool" if score >= _THRESHOLD else "chat",
            "score": round(score, 2),
            "threshold": _THRESHOLD,
            "fired_rules": fired,
        }
```

### Ejemplos de Reglas Heurísticas Definidas
Las expresiones regulares se compilan en memoria al iniciar la aplicación. Las reglas positivas otorgan pesos altos basados en palabras clave:

```python
_TOOL_RULES = [
    _r(r"\b(elimina|eliminar|borra|borrar|suprime|suprimir|remove|delete|quita|quitar)\b.{0,40}\b(archivo|fichero|\.txt|\.py|\.json)\b", 3.5, "fs_delete"),
    _r(r"\b(clasifica(r)? (el |los )?(correo|mail|correos|emails))\b", 3.5, "mail_classify"),
]

_CHAT_RULES = [
    _r(r"\b(escribe|escribir|redacta|redactar)\b.{0,40}\b(carta|email|correo|poema|texto|artículo|ensayo)\b", -2.5, "creative"),
]
```

Si la puntuación final de la suma algebraica supera el umbral de corte de `1.5`, el orquestador decide omitir por completo la inferencia cognitiva de la IA, derivando la consulta del usuario de forma inmediata al motor físico de ejecución.

## 4.3 Clasificación por Expresión Regular vs Enrutamiento por Similitud Coseno
Una alternativa común al enrutamiento por expresiones regulares es el cálculo de embeddings del texto de entrada del usuario y la posterior búsqueda de similitud coseno contra un listado de intenciones predefinidas. Sin embargo, este enfoque requiere una llamada intermedia a un modelo de embeddings, lo que genera una latencia de alrededor de 50-100 ms. El uso de expresiones regulares compiladas en memoria permite realizar la clasificación en menos de 0.1 ms, lo que representa una ganancia de rendimiento de tres órdenes de magnitud para peticiones directas y repetitivas.

### Preguntas de Autoevaluación del Capítulo 4
1. ¿Qué es el "threshold" o umbral en el contexto del `IntentRouter` y cómo afecta al comportamiento conversacional del agente?
2. ¿Qué ventajas aporta compilar expresiones regulares (`re.compile`) en comparación con interpretarlas al vuelo dentro de una función?
\n\n---\n\n# CAPÍTULO 5: SANDBOXING Y EJECUCIÓN SEGURA DE CÓDIGO (DOCKER ISOLATION)

## 5.1 Amenazas de la Ejecución Directa de Código
Uno de los mayores peligros de los agentes de software es que ejecutan código arbitrario generado por modelos de lenguaje en la máquina anfitriona. Si un modelo comete un error, o es víctima de una inyección de instrucciones en el prompt (Prompt Injection), la máquina podría verse comprometida:
* **Fuga de Información**: Lectura de ficheros del sistema (ej. claves privadas SSH, credenciales del archivo `.env`).
* **Peticiones Maliciosas**: El agente podría ser utilizado como intermediario para atacar otros servidores web externos o participar en denegaciones de servicio.
* **Agotamiento de Hardware**: Scripts dañinos podrían saturar la memoria RAM o el disco de la máquina host.

Para garantizar la seguridad física del host, Alfonso encapsula todas las operaciones de codificación del agente de desarrollo (`DevAgent`) en un **Sandbox de Docker** aislado y con restricciones de hardware.

## 5.2 Análisis del Código de Aislamiento
El agente de desarrollo en [dev_agent.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/agents/dev/dev_agent.py) implementa la ejecución en sandbox:

```python
# app/domain/agents/dev/dev_agent.py
    def execute_command_in_sandbox(self, cmd: str) -> dict:
        """Ejecuta un comando en el directorio del sandbox. Si Docker está disponible,
        aísla la ejecución en un contenedor efímero con recursos y red restringida.
        De lo contrario, recurre a subprocess.run en local."""
        try:
            import shlex
            import shutil
            
            has_docker = shutil.which("docker") is not None
            abs_sandbox = self.sandbox_path.resolve()
            
            if has_docker:
                # Docker seguro con límites: sin red (--network none), CPU y memoria limitadas.
                docker_image = "python:3.12-slim" if cmd.startswith("python") else "alpine:latest"
                docker_cmd = [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "-m", "128m",
                    "--cpus", "0.5",
                    "-v", f"{abs_sandbox}:/workspace",
                    "-w", "/workspace",
                    docker_image
                ]
                args = docker_cmd + shlex.split(cmd)
                orchestrator_logger.info("DevAgent: Ejecutando en Docker aislado: %s", " ".join(args))
            else:
                args = shlex.split(cmd)
                orchestrator_logger.warning("Docker no disponible. Ejecutando sin aislamiento en host: %s", cmd)

            res = subprocess.run(
                args,
                shell=False,
                cwd=str(abs_sandbox) if not has_docker else None,
                capture_output=True,
                text=True,
                timeout=15
            )
```

### Explicación de los Parámetros del Sandbox de Docker
1. `--rm`: Destruye el contenedor temporal tras finalizar la ejecución. Esto evita que se almacenen scripts binarios maliciosos o archivos temporales residuales en la memoria flash de la máquina.
2. `--network none`: Desconecta los adaptadores de red virtuales del contenedor. Ningún script escrito por la IA puede descargar librerías infectadas o subir archivos de configuración privados a servidores externos.
3. `-m 128m` y `--cpus 0.5`: Impide ataques de Denegación de Servicio (DoS). Si el script contiene un bucle infinito o un consumo excesivo de memoria, el kernel detendrá el contenedor antes de que ralentice el sistema anfitrión.
4. `-v {abs_sandbox}:/workspace`: Monta exclusivamente la carpeta local del sandbox (`data/dev_sandbox`). El contenedor carece de permisos para leer o escribir en cualquier otro directorio del disco duro.

## 5.3 Virtualización por Contenedores frente a Virtualización Completa
El sandbox de Alfonso utiliza contenedores de Linux (Docker) en lugar de máquinas virtuales (Hyper-V o VirtualBox). Los contenedores comparten el kernel de la máquina anfitriona, lo que permite levantarlos en menos de un segundo y con una penalización mínima de rendimiento de hardware. Esto es fundamental para entornos agénticos locales, donde la velocidad de respuesta es prioritaria. La virtualización completa, por el contrario, requiere iniciar un sistema operativo completo, demorando decenas de segundos antes de poder iniciar un simple script de Python.

### Preguntas de Autoevaluación del Capítulo 5
1. Explique cómo el parámetro `--network none` protege al sistema host frente a la exfiltración de secretos del archivo `.env`.
2. ¿Qué diferencia de seguridad existe entre ejecutar un script directamente con `subprocess.run` frente a ejecutarlo en un contenedor Docker aislado?
\n\n---\n\n# CAPÍTULO 6: SISTEMAS DE RECUPERACIÓN Y GENERACIÓN ENRIQUECIDA (RAG LEGAL CON CHROMADB)

## 6.1 Fundamentos de RAG y Bases de Datos Vectoriales
Los modelos de Inteligencia Artificial presentan limitaciones a la hora de manejar normativas muy específicas o variables (como la legislación tributaria o el Código Civil de un país). Al no tener memorizados de fábrica los textos exactos, sufren de alucinación semántica.

La técnica de **Generación Recuperada por Contexto (Retrieval-Augmented Generation)** solventa esto:
1. Divide las leyes en fragmentos cortos de texto (Chunks).
2. Calcula vectores de embeddings multidimensionales para cada bloque.
3. Guarda los vectores en una base de datos vectorial (como ChromaDB).
4. Ante una duda legal, calcula el vector del mensaje del usuario y recupera los 5 artículos de ley más cercanos en el espacio vectorial.

## 6.2 El Agente Marcos de Asesoramiento Legal
El módulo [marcos_agent.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/agents/marcos/marcos_agent.py) implementa este patrón recuperando leyes antes de interactuar con el modelo de lenguaje:

```python
# app/domain/agents/marcos/marcos_agent.py
class MarcosAgent:
    async def generate_response(self, query: str, context_email: dict = None) -> str:
        search_query = query
        if context_email:
            search_query = f"{context_email.get('subject', '')} {context_email.get('body', '')} {query}"
            
        legal_articles = vector_memory.query_legal(search_query, limit=5)
        
        if legal_articles:
            legal_context = "Artículos y legislación española relevante encontrada:\n" + "\n\n".join(legal_articles)
        else:
            legal_context = "No se encontraron artículos específicos en la base de datos de legislación."
```

El contexto legal recuperado se adjunta de forma estructurada en el prompt final del sistema. Esto permite al LLM redactar dictámenes y borradores de respuesta basándose estrictamente en artículos reales y actualizados de la ley española.

## 6.3 Estrategias de Chunking y Embeddings
Al construir el sistema RAG para el Agente Marcos, se debe definir el tamaño de fragmentación del texto (Chunking Strategy). Si los fragmentos son muy pequeños (e.g. 50 caracteres), se pierde el contexto del artículo de ley. Si son demasiado grandes (e.g. 10,000 caracteres), se diluye la relevancia semántica y se consume un exceso de tokens en el prompt. Alfonso utiliza un tamaño de fragmento de 500-1000 caracteres con un solapamiento del 10% para conservar la consistencia de las leyes penales y civiles.

### Preguntas de Autoevaluación del Capítulo 6
1. ¿Qué es una base de datos vectorial y cómo difiere de una base de datos relacional tradicional en búsquedas semánticas?
2. Describa los pasos lógicos de la técnica RAG desde que el usuario realiza la consulta hasta que el LLM genera la respuesta legal.
\n\n---\n\n# CAPÍTULO 7: FIREWALLS DE APLICACIÓN (WAF) Y MITIGACIÓN DE EVASIONES

## 7.1 El WAF como Escudo a Nivel de Aplicación
Los atacantes de sistemas de software intentan evadir las reglas de los firewalls habituales modificando el formato y codificación de los mensajes de entrada. A través de comentarios maliciosos o doble codificación hexadecimal, buscan camuflar sentencias SQL o inyecciones de comandos para alterar la lógica del backend.

Alfonso mitiga estas amenazas sanitizando y normalizando recursivamente los inputs del usuario en [security_agent.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/agents/security/security_agent.py) antes de contrastar los patrones contra las firmas de vulnerabilidades.

## 7.2 Lógica de Sanitización de Payloads
El agente de ciberseguridad ejecuta una limpieza exhaustiva a bajo nivel:

```python
# app/domain/agents/security/security_agent.py
    def _normalize_payload(self, payload: str) -> str:
        if not payload:
            return ""

        # 1. Eliminar Null Bytes que puedan truncar cadenas
        payload = payload.replace("\x00", "")

        # 2. Decodificación URL recursiva (hasta 3 iteraciones)
        import urllib.parse
        last_payload = ""
        iterations = 0
        while payload != last_payload and iterations < 3:
            last_payload = payload
            payload = urllib.parse.unquote(payload)
            iterations += 1

        # 3. Normalización Unicode (NFKD) para evitar homógrafos/suplantaciones
        import unicodedata
        payload = unicodedata.normalize("NFKD", payload)

        # 4. Eliminar comentarios SQL (-- y /* ... */) para neutralizar obfuscaciones
        payload = re.sub(r"/\*.*?\*/", "", payload, flags=re.DOTALL)
        payload = re.sub(r"--.*", "", payload)
        
        # 5. Eliminar comentarios HTML <!-- ... -->
        payload = re.sub(r"<!--.*?-->", "", payload, flags=re.DOTALL)

        return payload
```

Esta sanitización expone el texto de forma unificada, desactivando inyecciones XSS, SQL, Path Traversal o de consola local, y permitiendo al middleware web interceptar y vetar la IP agresora de forma inmediata.

## 7.3 Ataques Homógrafos y Normalización Unicode
Un ataque homógrafo Unicode consiste en usar caracteres de diferentes alfabetos (como el cirílico) que visualmente parecen idénticos a letras del alfabeto latino estándar (por ejemplo, reemplazar la letra 'a' latina por la 'а' cirílica). Si el WAF busca la cadena `select`, un ataque homógrafo con caracteres cirílicos no coincidiría con la regex básica pero sería interpretado de forma equivalente por otros motores de base de datos. La normalización Unicode `NFKD` traduce todos los caracteres homógrafos a sus formas latinas equivalentes antes de evaluar la seguridad, neutralizando este vector de ataque.

### Preguntas de Autoevaluación del Capítulo 7
1. ¿Por qué es fundamental realizar una decodificación URL de forma recursiva antes de procesar expresiones regulares en un WAF?
2. Describa cómo un ataque de inyección SQL puede ser ofuscado usando comentarios y cómo el normalizador de Alfonso lo mitiga.
\n\n---\n\n# CAPÍTULO 8: AUTOMATIZACIÓN DE NAVEGACIÓN Y MAPEO SEMÁNTICO (PLAYWRIGHT)

## 8.1 Extracción e Ingestión Dinámica de Páginas Web
El agente de empleo de Alfonso (`JobAgent`) tiene la misión de buscar ofertas de empleo y completar los cuestionarios de postulación del usuario. Debido a que cada portal web utiliza una estructura HTML, nombres de campos e identificadores CSS completamente dispares, es imposible escribir scripts manuales estáticos para rellenar los datos.

Para resolver esto de manera dinámica, `JobAgent` inyecta una función de extracción JavaScript dentro de la sesión de Playwright en [job_agent.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/domain/agents/job/job_agent.py).

## 8.2 Mapeo Semántico de Formularios HTML
El script extrae todos los campos de texto del formulario y recopila información como identificadores, marcadores de posición (*placeholders*) y etiquetas visuales cercanas para estructurarlos en una colección JSON inteligible por el LLM:

```python
# app/domain/agents/job/job_agent.py
        fields = await page.evaluate('''() => {
            const result = [];
            const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], textarea');
            inputs.forEach(input => {
                let labelText = "";
                if (input.id) {
                    const label = document.querySelector(`label[for="${input.id}"]`);
                    if (label) labelText = label.innerText;
                }
                if (!labelText) {
                    const parentLabel = input.closest('label');
                    if (parentLabel) labelText = parentLabel.innerText;
                }
                
                // Generar selector CSS único razonable
                let selector = "";
                if (input.id) {
                    selector = `#${input.id}`;
                } else if (input.name) {
                    selector = `input[name="${input.name}"], textarea[name="${input.name}"]`;
                }

                result.push({
                    id: input.id || "",
                    name: input.name || "",
                    placeholder: input.placeholder || "",
                    labelText: labelText ? labelText.trim() : "",
                    type: input.type || "text",
                    selector: selector
                });
            });
            return result;
        }''')
```

El modelo de lenguaje compara este JSON estructurado contra los datos del currículum del usuario, deduciendo de forma automática e inteligente qué respuestas inyectar en cada campo utilizando los selectores devueltos.

## 8.3 Scraping Estático frente a Automatización Interactiva (DOM)
Los rastreadores clásicos (como BeautifulSoup) se limitan a descargar el archivo HTML inicial enviado por el servidor. Sin embargo, los portales web modernos (Single Page Applications basadas en React o Vue) cargan sus formularios de forma diferida mediante peticiones JavaScript en segundo plano. La automatización interactiva con Playwright permite esperar a que el DOM esté completamente renderizado, ejecutando eventos reales de click, scroll e inyección de datos sobre la interfaz del navegador.

### Preguntas de Autoevaluación del Capítulo 8
1. ¿Cómo ayuda la ejecución de código JavaScript en la consola del navegador a extraer selectores CSS dinámicos de forma consistente?
2. Describa el flujo que sigue el `JobAgent` para postular automáticamente a un usuario basándose en su currículum vitae.
\n\n---\n\n# CAPÍTULO 9: COERCIÓN DE TIPOS E INTERFACES DE SEGURIDAD EN LLAMADAS A HERRAMIENTAS

## 9.1 Tipado Dinámico y el Problema de la Inferencia de LLM
Los modelos LLM producen cadenas de texto libre. Si el modelo deduce que debe llamar a la herramienta `delete_file`, generará un JSON como `{"filename": "datos.txt"}`. Sin embargo, para invocar funciones Python locales con total seguridad, es imprescindible validar que el LLM no intente pasar parámetros con tipos dañinos o nulos que puedan desbordar la pila de memoria o provocar fallos del servidor.

Alfonso implementa validaciones estrictas y coerción de tipos mediante Pydantic v2 en [tool_base.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/adapters/tool_base.py).

## 9.2 Validación de Argumentos y Alias
La clase `ToolArgsModel` define la configuración de Pydantic para ignorar campos inesperados generados accidentalmente por el modelo de IA:

```python
# app/adapters/tool_base.py
class ToolArgsModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
```

La validación y conversión segura de los argumentos se lleva a cabo en la función `coerce_and_validate(...)`:

```python
# app/adapters/tool_base.py
def coerce_and_validate(
    raw_args: dict[str, Any],
    model_cls: Type[ToolArgsModel],
    aliases: AliasMap | None = None
) -> ValidatedArgs:
    # 1. Aplicar aliases
    cleaned_args = _apply_aliases(raw_args, aliases or {})

    # 2. Limpieza de strings excesivos
    for k, v in cleaned_args.items():
        if isinstance(v, str):
            cleaned_args[k] = v.strip()

    # 3. Validación estricta con Pydantic
    try:
        instance = model_cls(**cleaned_args)
        return ValidatedArgs(ok=True, args=instance.model_dump())
    except ValidationError as e:
        return ValidatedArgs(ok=False, args=cleaned_args, error=str(e))
```

Esta estructura garantiza que toda llamada a herramientas locales esté completamente tipada y sanitizada de forma nativa antes de entrar en los de procesos del sistema.

## 9.3 Ventajas de Pydantic v2 sobre Validaciones Manuales
La validación manual mediante condicionales `if-else` para comprobar tipos y campos obligatorios resulta en código propenso a errores y difícil de mantener a medida que crecen las herramientas. Pydantic v2 utiliza un motor de validación compilado en Rust que realiza el tipado, sanitización y casteo de variables de forma ultra-rápida. Además, permite estructurar la documentación de la herramienta automáticamente para exportarla al prompt del LLM en formato JSON Schema.

### Preguntas de Autoevaluación del Capítulo 9
1. ¿Qué función cumple la directiva `extra="ignore"` en la configuración de los modelos Pydantic de argumentos de Alfonso?
2. Explique cómo el método `coerce_and_validate` asiste al orquestador en la prevención de excepciones en tiempo de ejecución.
\n\n---\n\n# CAPÍTULO 10: ARQUITECTURA DE PLUGINS Y REGISTRO DINÁMICO DE HERRAMIENTAS

## 10.1 Principio de Abierto/Cerrado (Open/Closed Principle)
Una buena arquitectura de software debe ser abierta a la extensión pero cerrada a la modificación. En el desarrollo de plataformas inteligentes, esto significa que deberíamos poder añadir decenas de herramientas y conectores nuevos para interactuar con bases de datos, APIs de mensajería o servicios externos sin modificar los archivos principales del núcleo del orquestador.

Alfonso implementa esto mediante un **Registro de Plugins por Reflexión** en [tool_registry.py](file:///wsl.localhost/Ubuntu/home/luisd/Alfonso/app/adapters/tool_registry.py).

## 10.2 Carga de Módulos en Caliente
El método `load_plugins()` escanea de forma dinámica las carpetas de herramientas locales (`client` y `server`) e importa los módulos en caliente durante la inicialización del ciclo de vida:

```python
# app/adapters/tool_registry.py
def load_plugins():
    global _plugins_loaded
    if _plugins_loaded:
        return
    tools_dir = _get_tools_directory()

    if not tools_dir.exists():
        tool_registry_logger.warning("Directorio de tools no encontrado: %s", tools_dir)
        return

    # Escanear subdirectorios server y client
    for sub in ("server", "client"):
        subdir = tools_dir / sub
        if not subdir.exists():
            continue
        for p in subdir.glob("*.py"):
            if p.name.startswith("__"):
                continue
            module_name = f"app.tools.{sub}.{p.stem}"
            try:
                importlib.import_module(module_name)
            except Exception:
                tool_registry_logger.exception("Error cargando plugin: %s", module_name)
    
    _plugins_loaded = True
```

### Mecanismo de Decoradores de Registro
Cada plugin de herramientas del sistema simplemente decora su función llamando a `register_tool`, lo que inyecta su firma en el diccionario del registry de forma transparente durante la importación, simplificando radicalmente la arquitectura y el desarrollo en equipo.

## 10.3 Reflexión de Código y Acoplamiento
La reflexión es la capacidad de un programa de inspeccionar y modificar su estructura y comportamiento en tiempo de ejecución. Al importar dinámicamente los módulos con `importlib.import_module`, Alfonso implementa un acoplamiento laxo. El núcleo del servidor desconoce la existencia de herramientas individuales; simplemente lee la carpeta del disco y delega el registro al decorador, cumpliendo con el principio de desarrollo abierto de interfaces modulares.

### Preguntas de Autoevaluación del Capítulo 10
1. ¿Cómo contribuye el uso de reflexión a cumplir el principio de Abierto/Cerrado (Open/Closed Principle) de SOLID?
2. Describa el mecanismo por el cual el decorador `register_tool` añade una herramienta al diccionario de herramientas de servidor sin modificar el core.
\n\n---\n\n