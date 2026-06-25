"""
Tests para Fase 1 (BaseTool + Pydantic).

Cubren el caso real visto en logs/errors.log:
    TypeError: create_file() got an unexpected keyword argument 'file_path'

En modo permisivo (default), `prepare_tool_args` debe recuperar esos args
en vez de dejar que el TypeError crudo llegue al usuario. En modo strict,
debe rechazarlos.
"""

import asyncio

import pytest

from app.core import tool_registry
from app.core.tool_base import coerce_and_validate
from app.tools.filesystem_tools import CreateFileArgs, ARGS_SCHEMAS


def test_permissive_recovers_known_alias():
    """file_path -> path es un alias explícito: debe recuperarse sin avisos raros."""
    schema, aliases = ARGS_SCHEMAS["create_file"]

    result = coerce_and_validate(
        tool_name="create_file",
        raw_args={"file_path": "notas.txt", "content": "hola"},
        schema=schema,
        aliases=aliases,
        mode="permissive",
    )

    assert result.ok is True
    assert result.args == {"path": "notas.txt", "content": "hola"}


def test_permissive_recovers_unknown_key_by_similarity():
    """Una clave nunca vista pero que CONTIENE el nombre del campo ('output_path')
    debe recuperarse vía heurística de similitud, sin necesidad de un alias exacto."""
    schema, aliases = ARGS_SCHEMAS["create_file"]

    result = coerce_and_validate(
        tool_name="create_file",
        raw_args={"output_path": "reporte.txt", "content": "datos"},
        schema=schema,
        aliases=aliases,
        mode="permissive",
    )

    assert result.ok is True
    assert result.args["path"] == "reporte.txt"
    assert result.warnings  # debe quedar constancia de la heurística aplicada


def test_permissive_ignores_unknown_extra_fields():
    schema, aliases = ARGS_SCHEMAS["create_file"]

    result = coerce_and_validate(
        tool_name="create_file",
        raw_args={"path": "a.txt", "content": "x", "campo_inventado": 123},
        schema=schema,
        aliases=aliases,
        mode="permissive",
    )

    assert result.ok is True
    assert "campo_inventado" not in result.args


def test_strict_mode_rejects_unknown_alias():
    schema, aliases = ARGS_SCHEMAS["create_file"]

    result = coerce_and_validate(
        tool_name="create_file",
        raw_args={"file_path": "notas.txt", "content": "hola"},
        schema=schema,
        aliases=aliases,
        mode="strict",
    )

    assert result.ok is False
    assert result.error


def test_tool_without_schema_passes_through_untouched():
    """Migración incremental: una tool sin esquema no se ve afectada en absoluto."""
    result = coerce_and_validate(
        tool_name="run_command",
        raw_args={"command": "ls -la"},
        schema=None,
        aliases=None,
        mode="permissive",
    )

    assert result.ok is True
    assert result.args == {"command": "ls -la"}


def test_prepare_tool_args_end_to_end_create_file(tmp_path, monkeypatch):
    """Camino completo: tool_registry.prepare_tool_args + ejecución real del tool."""
    tool_registry.load_plugins()

    target = tmp_path / "salida.txt"

    validated = tool_registry.prepare_tool_args(
        "create_file",
        {"file_path": str(target), "content": "contenido de prueba"},
    )

    assert validated.ok is True

    create_file_tool = tool_registry.get_tool("create_file")
    result = asyncio.run(create_file_tool(**validated.args))

    assert result["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "contenido de prueba"