import re
from pathlib import Path

# Metadata map
METADATA = {
    "app/config.py": {
        "title": "CONFIG — Configuración global de la aplicación.",
        "que_hace": "Define y expone la clase Settings cargando variables de entorno, nombres de modelos de IA y rutas de prompts utilizando pydantic_settings.",
        "cuando": "Al inicializar la aplicación para configurar la dirección de Ollama, el modelo cargado y demás constantes clave de Alfonso.",
        "como": "Heredando de BaseSettings para realizar validación estricta de tipos y leer opcionalmente archivos .env.",
        "relacionado": [
            "app/main.py (consume los settings para inicializar FastAPI y los servicios)",
            "app/core/llm_client.py (utiliza la URL de Ollama y el nombre del modelo)"
        ]
    },
    "app/core/actions.py": {
        "title": "ACTIONS — Acciones asíncronas y operaciones del orquestador.",
        "que_hace": "Define tareas de utilidad y validaciones ejecutadas por el orquestador durante el ciclo de vida del plan.",
        "cuando": "Durante la ejecución del planificador para verificar el estado del cliente, resolver tareas complejas y realizar acciones genéricas.",
        "como": "Mediante funciones asíncronas de Python que interactúan con el puente WebSocket y el estado del sistema.",
        "relacionado": [
            "app/core/planner_orchestrator.py (invoca estas acciones durante su pipeline)",
            "app/core/alfonso_bridge.py (verifica el estado de las conexiones websocket activas)"
        ]
    },
    "app/core/alfonso_bridge.py": {
        "title": "ALFONSO BRIDGE — Puente de comunicación en tiempo real con el cliente.",
        "que_hace": "Administra las conexiones de sockets en segundo plano y canaliza mensajes y comandos estructurados entre el servidor y la interfaz de usuario local.",
        "cuando": "Durante todo el ciclo de vida del servidor web (lifespan) y al procesar eventos interactivos.",
        "como": "Implementando un servidor WebSocket asíncrono y colas de control para emitir peticiones y sincronizaciones en formato JSON.",
        "relacionado": [
            "app/main.py (inicia y detiene el bridge en los eventos de lifespan)",
            "app/api/routes.py (actualiza la información del cliente conectado y sincroniza el calendario)"
        ]
    },
    "app/core/calendar_db.py": {
        "title": "CALENDAR DB — Abstracción de base de datos SQLite para calendario nativo.",
        "que_hace": "Proporciona funciones CRUD para almacenar y gestionar los eventos de la agenda local.",
        "cuando": "Al listar, crear, actualizar o eliminar citas a través de las herramientas del planificador o endpoints REST.",
        "como": "Ejecutando consultas SQL directas en una base de datos SQLite persistente local.",
        "relacionado": [
            "app/api/routes.py (expone endpoints REST para interactuar con esta base de datos)",
            "app/tools/calendar_tools.py (expone estas funciones en forma de herramientas para el LLM)"
        ]
    },
    "app/core/http_client.py": {
        "title": "HTTP CLIENT — Cliente HTTP asíncrono global.",
        "que_hace": "Expone un pool único de conexiones HTTP asíncronas reutilizables por toda la aplicación.",
        "cuando": "Al realizar llamadas externas hacia la API de Ollama o cualquier servicio HTTP de terceros.",
        "como": "Instanciando un objeto httpx.AsyncClient global y manejando timeouts para prevenir bloqueos.",
        "relacionado": [
            "app/core/llm_client.py (utiliza este cliente para comunicarse con Ollama)",
            "app/core/agents/dev/dev_agent.py (utiliza este cliente para realizar llamadas API directas)"
        ]
    },
    "app/core/intent_router.py": {
        "title": "INTENT ROUTER — Enrutador heurístico de intenciones.",
        "que_hace": "Analiza la consulta del usuario para clasificarla rápidamente en una intención o delegar directamente a un agente específico.",
        "cuando": "Al inicio de cada llamada al endpoint de chat para determinar la ruta óptima de procesamiento.",
        "como": "Mediante coincidencia semántica y palabras clave específicas con expresiones regulares rápidas.",
        "relacionado": [
            "app/core/planner_orchestrator.py (invoca este router al inicio de su pipeline)",
            "app/core/agents/dev/dev_agent.py (recibe delegaciones si el intent es desarrollo)",
            "app/core/agents/marcos/marcos_agent.py (recibe delegaciones si el intent es legal)"
        ]
    },
    "app/core/llm_client.py": {
        "title": "LLM CLIENT — Cliente del modelo de lenguaje (Ollama).",
        "que_hace": "Gestiona la comunicación con el servidor Ollama local para generar texto, completar chats, estructurar JSON y precalentar el modelo.",
        "cuando": "Siempre que el orquestador, router o agentes requieran capacidades cognitivas de inferencia del LLM.",
        "como": "Formateando payloads HTTP compatibles con la API `/api/chat` de Ollama y llamándolos con app/core/http_client.py.",
        "relacionado": [
            "app/core/http_client.py (provee el cliente HTTP subyacente para las peticiones)",
            "app/core/planner_orchestrator.py (usa este cliente para planificar y responder en el chat)"
        ]
    },
    "app/core/mail_db.py": {
        "title": "MAIL DB — Abstracción de base de datos SQLite para correo electrónico.",
        "que_hace": "Administra la base de datos local de correos electrónicos, ofreciendo filtros por importancia, remitente, y funciones para marcar como leído o sembrar datos simulados.",
        "cuando": "Al gestionar correos desde los endpoints HTTP o al invocar herramientas de clasificación y redacción.",
        "como": "Realizando operaciones SQL directas usando sqlite3 sobre una tabla local de correos persistidos.",
        "relacionado": [
            "app/api/routes.py (expone los endpoints HTTP `/mail` para interactuar con esta base de datos)",
            "app/tools/mail_tools.py (utiliza estas funciones para enviar, clasificar y responder emails)"
        ]
    },
    "app/core/memory.py": {
        "title": "MEMORY — Memoria de diálogo y almacenamiento de historial.",
        "que_hace": "Mantiene el historial de la conversación actual por sesión en memoria volátil (RAM).",
        "cuando": "Durante el procesamiento de consultas para recuperar mensajes previos del usuario y el asistente e inyectarlos en el prompt.",
        "como": "Almacenando listas de mensajes estructurados en un diccionario indexado por `session_id` con hilos seguros.",
        "relacionado": [
            "app/core/planner_orchestrator.py (consulta el historial para contextualizar al modelo)",
            "app/api/routes.py (ofrece endpoints para leer, listar y borrar historiales por sesión)"
        ]
    },
    "app/core/metrics.py": {
        "title": "METRICS — Recolección de métricas internas del servidor.",
        "que_hace": "Realiza un seguimiento del conteo de solicitudes HTTP, incidencias de errores y latencias de respuesta del sistema.",
        "cuando": "En cada petición HTTP interceptada por el middleware de la aplicación o al ocurrir una excepción controlada.",
        "como": "Incrementando variables globales seguras en memoria y devolviendo un snapshot agregado en formato JSON.",
        "relacionado": [
            "app/main.py (actualiza las métricas a través de middlewares y manejadores de errores)",
            "app/api/routes.py (expone el endpoint GET `/metrics` para monitorear el rendimiento)"
        ]
    },
    "app/core/prompt_generator.py": {
        "title": "PROMPT GENERATOR — Administrador de plantillas de prompts de Alfonso.",
        "que_hace": "Precarga, almacena y formatea las instrucciones del sistema (prompts) requeridas por los modelos de IA.",
        "cuando": "Al arrancar la aplicación y antes de enviar payloads de chat o planificación al LLM.",
        "como": "Cargando los archivos de texto planos de app/prompts/ y aplicando reemplazos dinámicos.",
        "relacionado": [
            "app/core/llm_client.py (consume los prompts de sistema para pasarlos al LLM)",
            "app/main.py (precarga los prompts de chat y herramientas durante el lifespan)"
        ]
    },
    "app/core/tool_base.py": {
        "title": "TOOL BASE — Clase base abstracta de herramientas de Alfonso.",
        "que_hace": "Define el contrato y estructura formal para todas las herramientas del sistema que el LLM puede descubrir y ejecutar.",
        "cuando": "Al registrar una nueva herramienta para asegurar que cuenta con descripción, parámetros y validaciones de tipos.",
        "como": "Utilizando tipado de Python y metadatos de funciones para extraer un esquema JSON representativo.",
        "relacionado": [
            "app/core/tool_registry.py (mantiene y valida la lista de herramientas registradas)",
            "app/tools/ (todos los módulos de herramientas heredan o implementan este estándar)"
        ]
    },
    "app/core/tool_registry.py": {
        "title": "TOOL REGISTRY — Registro centralizado de herramientas.",
        "que_hace": "Almacena, expone y permite recuperar de manera unificada las herramientas del sistema y del cliente para su uso por el planificador.",
        "cuando": "Al inicializar la aplicación (descubrimiento) y al recuperar esquemas de herramientas para el LLM.",
        "como": "Manteniendo un diccionario global de herramientas registradas mediante decoradores.",
        "relacionado": [
            "app/core/planner_orchestrator.py (consulta el registro para obtener los esquemas y ejecutar herramientas)",
            "app/api/routes.py (expone GET `/tools` para listar las herramientas cargadas)"
        ]
    },
    "app/core/vector_memory.py": {
        "title": "VECTOR MEMORY — Interfaz con la base de datos vectorial ChromaDB.",
        "que_hace": "Gestiona búsquedas semánticas y almacenamiento de documentos técnicos y legislativos en ChromaDB.",
        "cuando": "Durante la delegación a agentes (MarcosAgent o DevAgent) para añadir contexto relevante al prompt.",
        "como": "Conectándose a una base de datos local persistente ChromaDB e indexando datos en colecciones (`dev_knowledge` y `legal_knowledge`).",
        "relacionado": [
            "app/core/agents/dev/dev_agent.py (consulta pautas de código en dev_knowledge)",
            "app/core/agents/marcos/marcos_agent.py (consulta leyes en legal_knowledge)"
        ]
    },
    "app/schemas/chat.py": {
        "title": "CHAT SCHEMAS — Modelos de datos para chat de Alfonso.",
        "que_hace": "Define las estructuras Pydantic utilizadas para el envío e intercambio de mensajes de chat.",
        "cuando": "Al serializar/deserializar información de entrada y salida del endpoint /chat.",
        "como": "Heredando de BaseModel de Pydantic para validar campos obligatorios y opcionales.",
        "relacionado": [
            "app/api/routes.py (utiliza estos esquemas en los payloads de endpoints REST)"
        ]
    },
    "app/tools/__init__.py": {
        "title": "TOOLS INIT — Registro global de herramientas de Alfonso.",
        "que_hace": "Importa de forma automática todos los módulos del paquete de herramientas para disparar el decorador `@tool` y registrarlos.",
        "cuando": "Al arrancar el servidor web para registrar todas las funciones ejecutables.",
        "como": "Realizando importaciones absolutas de todos los módulos de herramientas en el paquete.",
        "relacionado": [
            "app/core/tool_registry.py (almacena el registro global de estas herramientas)"
        ]
    },
    "app/tools/browser_tools.py": {
        "title": "BROWSER TOOLS — Herramientas de navegación web basadas en Playwright.",
        "que_hace": "Implementa herramientas para interactuar con sitios web (navegación, clics, búsquedas, rellenar formularios, scroll y screenshots).",
        "cuando": "Cuando el orquestador ejecuta tareas de investigación en la web en nombre del usuario.",
        "como": "Inicializando una sesión interactiva en segundo plano con Playwright y exponiendo llamadas asíncronas.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)",
            "app/api/routes.py (expone endpoints directos de control de navegador)"
        ]
    },
    "app/tools/calendar_tools.py": {
        "title": "CALENDAR TOOLS — Herramientas para la gestión de citas de Alfonso.",
        "que_hace": "Expone las funciones CRUD de base de datos de calendario para que el LLM las invoque.",
        "cuando": "Durante la ejecución del planificador para buscar, agendar o borrar eventos.",
        "como": "Mediante llamadas directas a las funciones asíncronas y síncronas de app/core/calendar_db.py.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)",
            "app/core/calendar_db.py (contiene las operaciones SQLite CRUD reales)"
        ]
    },
    "app/tools/command_executor.py": {
        "title": "COMMAND EXECUTOR — Herramientas de ejecución de comandos.",
        "que_hace": "Permite al planificador ejecutar comandos del sistema directamente en la terminal local de forma controlada.",
        "cuando": "Cuando el planificador necesita interactuar con servicios del SO o realizar tareas operativas complejas.",
        "como": "Invocando el módulo estándar `subprocess` de Python de forma asíncrona.",
        "relacionado": [
            "app/core/tool_registry.py (registra esta herramienta)"
        ]
    },
    "app/tools/computer_use_tools.py": {
        "title": "COMPUTER USE TOOLS — Control del sistema operativo e interactividad OSWorld.",
        "que_hace": "Ofrece herramientas de simulación humana: clics, movimiento de ratón, pulsación de teclas, OCR y screenshots de la pantalla activa.",
        "cuando": "Cuando el planificador requiere manipular la interfaz gráfica del servidor.",
        "como": "Usando PyAutoGUI para controlar periféricos de entrada y Tesseract (pytesseract) para reconocimiento óptico de caracteres.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)",
            "app/api/routes.py (expone endpoints directos bajo el prefijo `/computer`)"
        ]
    },
    "app/tools/filesystem_tools.py": {
        "title": "FILESYSTEM TOOLS — Manipulación del sistema de archivos local.",
        "que_hace": "Permite listar directorios, buscar texto en archivos, leer y escribir datos en disco.",
        "cuando": "Cuando el planificador requiere explorar archivos locales, crear scripts o modificar la base de código.",
        "como": "Encapsulando llamadas estándar de Python como `os`, `shutil` y `pathlib`.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)"
        ]
    },
    "app/tools/memory_tools.py": {
        "title": "MEMORY TOOLS — Acceso a la base de hechos y memoria semántica.",
        "que_hace": "Expone herramientas para buscar u registrar información factual de largo plazo en ChromaDB.",
        "cuando": "Durante la ejecución de planes de Alfonso para recordar u almacenar hechos de forma semántica.",
        "como": "Llamando a las funciones expuestas por `app/core/vector_memory.py`.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)",
            "app/core/vector_memory.py (contiene el motor de búsqueda ChromaDB)"
        ]
    },
    "app/tools/system_tools.py": {
        "title": "SYSTEM TOOLS — Herramientas auxiliares del sistema operativo.",
        "que_hace": "Proporciona la hora del sistema y la capacidad de pausar temporalmente la ejecución.",
        "cuando": "Cuando el planificador requiere datos temporales o realizar esperas en bucles de herramientas.",
        "como": "Utilizando los módulos estándar `time` y `datetime` de Python.",
        "relacionado": [
            "app/core/tool_registry.py (registra estas herramientas)"
        ]
    },
    "app/utils/dev_seeder.py": {
        "title": "DEV SEEDER — Inyección inicial de conocimiento técnico.",
        "que_hace": "Lee archivos locales con plantillas y pautas de diseño de software y los indexa en ChromaDB.",
        "cuando": "Se ejecuta de manera manual para sembrar o inicializar el conocimiento disponible para DevAgent.",
        "como": "Analizando archivos y subiéndolos mediante el cliente persistente de ChromaDB.",
        "relacionado": [
            "app/core/vector_memory.py (define el cliente y las colecciones donde se guardan los datos)"
        ]
    },
    "app/utils/legal_seeder.py": {
        "title": "LEGAL SEEDER — Inyección inicial de conocimiento legislativo.",
        "que_hace": "Segmenta e inyecta la Constitución Española, Código Civil y Código Penal en la base de datos ChromaDB.",
        "cuando": "Se ejecuta de manera manual para sembrar o inicializar el conocimiento legal de MarcosAgent.",
        "como": "Procesando documentos planos txt e indexando los fragmentos en la colección legal de ChromaDB.",
        "relacionado": [
            "app/core/vector_memory.py (almacena y expone la búsqueda sobre esta colección)"
        ]
    },
    "app/utils/logger.py": {
        "title": "LOGGER — Configuración del registro de logs.",
        "que_hace": "Define e inicializa la configuración de logs con rotación diaria para la app, el planificador y los errores.",
        "cuando": "Al inicio de la aplicación y a lo largo de toda la ejecución de cualquier script del servidor.",
        "como": "Configurando handlers de la biblioteca estándar `logging` e inyectando request IDs.",
        "relacionado": [
            "app/main.py (middleware HTTP utiliza el logger para registrar peticiones entrantes)"
        ]
    },
    "app/utils/timer.py": {
        "title": "TIMER — Medición precisa de latencias y tiempos de ejecución.",
        "que_hace": "Expone un administrador de contexto para medir la duración de ejecuciones de código.",
        "cuando": "Al registrar latencias de endpoints REST o llamadas a herramientas.",
        "como": "Usando `time.perf_counter()` en los métodos especiales `__enter__` y `__exit__` de Python.",
        "relacionado": [
            "app/api/routes.py (mide la latencia de /chat y herramientas de Playwright)"
        ]
    }
}

def format_docstring(filepath, data):
    title = data["title"]
    que_hace = data["que_hace"]
    cuando = data["cuando"]
    como = data["como"]
    relacionados_str = "\n".join(f"- {r}" for r in data["relacionado"])
    
    return f'''"""
{title}

¿QUÉ HACE?
{que_hace}

¿CUÁNDO LO HACE?
{cuando}

¿CÓMO LO HACE?
{como}

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
{relacionados_str}
"""
'''

def update_file(filepath, data):
    p = Path(filepath)
    if not p.exists():
        print(f"File {filepath} not found.")
        return
        
    content = p.read_text(encoding="utf-8")
    new_docstring = format_docstring(filepath, data)
    
    # Check if file already starts with a docstring
    if content.strip().startswith('"""'):
        # Find the end of the first docstring
        match = re.search(r'^"""(.*?)"""', content, re.DOTALL)
        if match:
            # Replace it
            content = content.replace(match.group(0), new_docstring.strip(), 1)
        else:
            # Append if malformed
            content = new_docstring + "\n" + content
    else:
        # Just prepend it
        content = new_docstring + "\n" + content
        
    p.write_text(content, encoding="utf-8")
    print(f"Updated docstring for {filepath}")

if __name__ == "__main__":
    for filepath, data in METADATA.items():
        update_file(filepath, data)
