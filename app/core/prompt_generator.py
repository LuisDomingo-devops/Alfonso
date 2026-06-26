import inspect

from app.core.tool_registry import list_tools, get_callable_tool_function


def generate_tool_prompt() -> str:
    """
    Genera el TOOL_PROMPT automáticamente desde el registry.
    Una sola línea por tool, formato canónico, args tomados de la
    firma real de la función (fuente única de verdad).
    """
    header = (
        "OUTPUT: JSON only. No text. No markdown. No explanation.\n\n"
        "MANDATORY FORMAT (always use exactly this structure):\n"
        '{"tool":"TOOL_NAME","args":{...}}\n\n'
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