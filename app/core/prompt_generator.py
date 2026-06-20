from app.core.tool_registry import list_tools, get_callable_tool_function


def generate_tool_prompt() -> str:
    """
    Genera el TOOL_PROMPT automáticamente desde el registry.
    Fuente única de verdad.
    """

    tools = list_tools()

    header = (
        "OUTPUT: JSON only. No text. No markdown. No explanation.\n\n"
        "MANDATORY FORMAT:\n"
        '{"tool":"TOOL_NAME","args":{...}}\n\n'
        "TOOLS:\n"
    )

    tool_blocks = []

    for tool_name in tools:
        func = get_callable_tool_function(tool_name)

        if not func:
            continue

        meta = getattr(func, "meta", None)

        description = ""
        args = ""

        if meta:
            description = meta.get("description", "")
            args_dict = meta.get("args", {})

            args_lines = []
            for k, v in args_dict.items():
                args_lines.append(f"- {k}: {v}")

            args = "\n".join(args_lines)

        tool_block = f"""{{"tool":"{tool_name}","args":{{...}}}}
{tool_name}:
{description}
args:
{args}
"""

        tool_blocks.append(tool_block)

    return header + "\n".join(tool_blocks)