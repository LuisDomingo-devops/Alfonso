"""
PROMPT GENERATOR — Administrador de plantillas de prompts de Alfonso.

¿QUÉ HACE?
Precarga, almacena y formatea las instrucciones del sistema (prompts) requeridas por los modelos de IA.

¿CUÁNDO LO HACE?
Al arrancar la aplicación y antes de enviar payloads de chat o planificación al LLM.

¿CÓMO LO HACE?
Cargando los archivos de texto planos de app/prompts/ y aplicando reemplazos dinámicos.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/llm_client.py (consume los prompts de sistema para pasarlos al LLM)
- app/main.py (precarga los prompts de chat y herramientas durante el lifespan)
"""

import inspect
import os
import platform
from pathlib import Path

from app.adapters.tool_registry import list_tools, get_callable_tool_function


def get_client_context_str() -> str:
    """
    Obtiene la cadena formateada con el contexto dinámico del entorno cliente de Windows
    (RAM, resolución de pantalla, dispositivos de audio, y estructura de archivos del Escritorio).
    """
    from app.adapters.alfonso_bridge import bridge as alfonso_bridge

    # Intentar obtener info del cliente conectado al bridge o fallback a last_client_info.json
    client_info = alfonso_bridge.client_info
    
    if not client_info:
        try:
            import json
            if os.path.exists("data/last_client_info.json"):
                with open("data/last_client_info.json", "r", encoding="utf-8") as f:
                    client_info = json.load(f)
        except Exception:
            pass
            
    if client_info:
        sys_name = client_info.get("system", platform.system())
        username = client_info.get("username", Path.home().name)
        home_dir_str = client_info.get("home", str(Path.home().resolve()))
        current_dir_str = client_info.get("cwd", str(Path.cwd().resolve()))
        is_wsl = "microsoft" in client_info.get("release", "").lower()
    else:
        # Fallback al contexto del servidor (WSL)
        sys_name = platform.system()
        username = Path.home().name
        home_dir_str = str(Path.home().resolve())
        current_dir_str = str(Path.cwd().resolve())
        is_wsl = False
        try:
            is_wsl = "microsoft" in platform.uname().release.lower() or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")
        except Exception:
            pass

    # Normalizar barras a barra inclinada
    home_dir_str = home_dir_str.replace("\\", "/")
    current_dir_str = current_dir_str.replace("\\", "/")

    context_lines = [
        "SYSTEM CONTEXT (TARGET EXECUTION ENVIRONMENT):",
        f"- Operating System: {sys_name} {'(WSL/Ubuntu)' if is_wsl else ''}",
        f"- Active Username: {username}",
        f"- Current Workspace Directory: {current_dir_str}",
        f"- User Home Directory: {home_dir_str}",
    ]
    
    if sys_name == "Windows":
        context_lines.extend([
            f"- User Desktop Directory: {home_dir_str}/Desktop",
            f"- User Documents Directory: {home_dir_str}/Documents",
        ])
    elif is_wsl:
        # Rutas comunes de Windows mapeadas en WSL
        context_lines.extend([
            f"- Mapped Windows User Home (WSL): /mnt/c/Users/{username}",
            f"- Mapped Windows Desktop Path: /mnt/c/Users/{username}/Desktop",
            f"- Mapped Windows Documents Path: /mnt/c/Users/{username}/Documents",
        ])
    else:
        context_lines.extend([
            f"- User Desktop Directory: {home_dir_str}/Desktop",
            f"- User Documents Directory: {home_dir_str}/Documents",
        ])

    # Inyectar características de hardware y archivos del escritorio si están disponibles
    if client_info:
        ram = client_info.get("ram_total_gb")
        if ram:
            context_lines.append(f"- Total Client System RAM: {ram} GB")
        res = client_info.get("screen_resolution")
        if res:
            context_lines.append(f"- Client Screen Resolution: {res}")
        audio = client_info.get("audio_devices")
        if audio:
            context_lines.append(f"- Client Input Audio Devices: {audio.get('input', [])}")
            context_lines.append(f"- Client Output Audio Devices: {audio.get('output', [])}")
        desktop_items = client_info.get("desktop_structure")
        if desktop_items:
            context_lines.append(f"- Client Desktop File/Folder List: {desktop_items}")
        
    return "\n".join(context_lines)


def generate_tool_prompt() -> str:
    """
    Genera el TOOL_PROMPT automáticamente desde el registry,
    además de inyectar contexto dinámico sobre el sistema operativo,
    el usuario y las rutas clave del entorno actual.
    """
    context_str = get_client_context_str()

    header = (
        "OUTPUT: JSON only. No text. No markdown. No explanation.\n"
        "You MUST output a valid JSON object matching the format below. Never output sentences or explanations.\n\n"
        f"{context_str}\n\n"
        "CRITICAL PATH RESOLUTION RULES:\n"
        "1. If the user mentions 'desktop' or 'escritorio', you MUST use the exact desktop path from the context lines above.\n"
        "2. If the user mentions 'documents' or 'documentos', you MUST use the exact documents path from the context lines above.\n"
        "3. Do NOT default to Linux paths like '/home/...' if the active operating system in the context is Windows and the user is requesting standard system actions.\n"
        "4. Always normalize paths to forward slashes '/' when constructing JSON arguments.\n\n"
        "MANDATORY FORMAT (always use exactly this structure):\n"
        '{"tool":"TOOL_NAME","args":{...}}\n\n'
        "EXAMPLES:\n"
        'User: crea una carpeta en la ruta C:/Users/luisd/Desktop/PruebaManual\n'
        'Output: {"tool":"create_directory","args":{"path":"C:/Users/luisd/Desktop/PruebaManual"}}\n\n'
        'User: crea un archivo en la ruta C:/Users/luisd/Desktop/PruebaManual/prueba.txt que diga Hola Mundo\n'
        'Output: {"tool":"create_file","args":{"path":"C:/Users/luisd/Desktop/PruebaManual/prueba.txt","content":"Hola Mundo"}}\n\n'
        'User: dentro de la carpeta PruebaManual crea un archivo que se llame notas.txt\n'
        'Output: {"tool":"create_file","args":{"path":"C:/Users/luisd/Desktop/PruebaManual/notas.txt","content":""}}\n\n'
        'User: escribe en el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt que funciona de maravilla\n'
        'Output: {"tool":"append_file","args":{"path":"C:/Users/luisd/Desktop/PruebaManual/prueba.txt","content":"que funciona de maravilla"}}\n\n'
        'User: lee el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt\n'
        'Output: {"tool":"read_file","args":{"path":"C:/Users/luisd/Desktop/PruebaManual/prueba.txt"}}\n\n'
        'User: renombra el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt a C:/Users/luisd/Desktop/PruebaManual/prueba_ok.txt\n'
        'Output: {"tool":"rename_file","args":{"path":"C:/Users/luisd/Desktop/PruebaManual/prueba.txt","new_name":"prueba_ok.txt"}}\n\n'
        'User: elimina la carpeta C:/Users/luisd/Desktop/PruebaManual\n'
        'Output: {"tool":"delete_directory","args":{"path":"C:/Users/luisd/Desktop/PruebaManual"}}\n\n'
        "TOOLS:\n"
    )

    lines = []
    for tool_name in list_tools():
        func = get_callable_tool_function(tool_name)

        try:
            params = inspect.signature(func).parameters
            arg_names = [
                name for name, p in params.items()
                if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
        except (TypeError, ValueError):
            arg_names = []

        args_preview = ",".join(f'"{a}":...' for a in arg_names)
        
        # Obtener la primera línea del docstring para orientar al modelo sobre la función de la herramienta
        doc = inspect.getdoc(func) or ""
        doc_line = doc.split("\n")[0].strip() if doc else ""
        desc = f"  # {doc_line}" if doc_line else ""
        
        lines.append(f'{{"tool":"{tool_name}","args":{{{args_preview}}}}}{desc}')

    return header + "\n".join(lines)