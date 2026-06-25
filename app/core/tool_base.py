"""
tool_base.py — Fase 1 (BaseTool + Pydantic)

Contexto del problema:
    El modelo actual (qwen2.5:1.5b) produce JSON de tool poco fiable:
    nombres de campo equivocados (`file_path` en vez de `path`), JSON
    truncado, claves en español/inglés mezcladas, etc. (ver logs/errors.log).

    Meter validación Pydantic ESTRICTA ahora mismo, antes de arreglar el
    extractor de JSON (`extract_json_robust` en llm_client.py), no soluciona
    nada: simplemente cambia un `TypeError: create_file() got an unexpected
    keyword argument 'file_path'` (que ya fallaba) por un `ValidationError`
    (que también falla). El número de "tool no encontrada / args inválidos"
    NO bajaría — probablemente subiría, porque Pydantic estricto también
    rechaza tipos casi-correctos (ej. "true" en vez de True) que el código
    actual aceptaba sin pestañear.

    Por eso esta Fase 1 introduce la infraestructura (BaseTool + esquemas
    Pydantic) pero en modo PERMISIVO por defecto:
        - alias conocidos se remapean (file_path -> path, contenido -> content...)
        - campos desconocidos se ignoran en vez de fallar
        - solo se devuelve error si, tras los intentos de recuperación,
          de verdad no se puede construir el modelo (p.ej. falta un campo
          obligatorio y no hay ningún alias/heurística que lo rellene)

    El modo se controla con `settings.TOOL_VALIDATION_MODE`:
        "permissive" (default) -> el comportamiento descrito arriba
        "strict"               -> validación Pydantic estándar, sin alias
                                   ni tolerancia a campos extra. Pensado
                                   para Fase 2, cuando el extractor de JSON
                                   ya sea fiable y tenga sentido rechazar
                                   args mal formados en vez de adivinarlos.

    Migración incremental: un tool sin esquema registrado en
    `ARGS_SCHEMAS` sigue funcionando exactamente igual que hoy (sin
    ningún tipo de validación) — esto permite ir añadiendo esquemas
    tool por tool sin romper nada de golpe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from app.utils.logger import attach_request_id, tool_registry_logger


# ---------------------------------------------------------------------------
# Modelo base para esquemas de argumentos de tools
# ---------------------------------------------------------------------------

class ToolArgsModel(BaseModel):
    """
    Clase base para los esquemas Pydantic de args de cada tool.

    extra="ignore": en modo permisivo, cualquier campo que el LLM invente
    y que no esté declarado en el esquema simplemente se descarta, en vez
    de provocar un error de validación (Pydantic v2 con extra="forbid" o
    "allow"+strict rechazaría/colaría basura).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# Tipo de un alias map: {"alias_que_puede_inventar_el_llm": "campo_real"}
AliasMap = dict[str, str]


# ---------------------------------------------------------------------------
# Resultado de la validación/coerción
# ---------------------------------------------------------------------------

@dataclass
class ValidatedArgs:
    ok: bool
    args: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# BaseTool — opcional, para tools que se quieran escribir como clase
# ---------------------------------------------------------------------------

class BaseTool:
    """
    Envoltorio opcional para definir una tool como clase en vez de función
    suelta. No es obligatorio usarlo: el registry sigue aceptando funciones
    async normales (ver app/tools/*.py). Sirve para tools nuevas que quieran
    declarar su esquema de args y su alias map junto a la lógica, en lugar
    de en un diccionario `ARGS_SCHEMAS` aparte.
    """

    name: str
    args_model: Type[ToolArgsModel] = ToolArgsModel
    aliases: AliasMap = {}

    async def execute(self, **kwargs) -> dict:  # pragma: no cover - interfaz
        raise NotImplementedError

    async def __call__(self, **kwargs) -> dict:
        return await self.execute(**kwargs)


# ---------------------------------------------------------------------------
# Heurísticas de recuperación en modo permisivo
# ---------------------------------------------------------------------------

def _apply_aliases(raw_args: dict[str, Any], aliases: AliasMap) -> dict[str, Any]:
    """Remapea claves alias -> nombre real de campo del esquema."""
    if not aliases:
        return dict(raw_args)

    mapped: dict[str, Any] = {}
    for key, value in raw_args.items():
        real_key = aliases.get(key, key)
        # Si el campo real aún no tiene valor (o el alias es más específico
        # que uno ya puesto), lo asignamos. No pisamos un valor ya correcto.
        if real_key not in mapped:
            mapped[real_key] = value
    return mapped


def _missing_required_fields(model_cls: Type[BaseModel], present: set[str]) -> list[str]:
    missing = []
    for field_name, field_info in model_cls.model_fields.items():
        if field_info.is_required() and field_name not in present:
            missing.append(field_name)
    return missing


def _best_effort_fill(
    model_cls: Type[BaseModel],
    mapped_args: dict[str, Any],
    unused_raw_args: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    """
    Último intento antes de rendirse en modo permisivo: si falta un campo
    obligatorio, busca entre las claves del payload original que no se
    hayan usado todavía algo cuyo nombre se "parezca" al campo que falta
    (substring case-insensitive). Esto cubre casos como un LLM mandando
    "nombre_archivo" para lo que el esquema llama "path", sin tener que
    mantener una lista infinita de alias exactos.
    """
    missing = _missing_required_fields(model_cls, set(mapped_args.keys()))
    if not missing:
        return mapped_args

    result = dict(mapped_args)
    for field_name in missing:
        for raw_key, raw_value in list(unused_raw_args.items()):
            if field_name.lower() in raw_key.lower() or raw_key.lower() in field_name.lower():
                result[field_name] = raw_value
                warnings.append(
                    f"campo '{field_name}' rellenado desde clave no reconocida '{raw_key}' "
                    "(modo permisivo, heurística por similitud de nombre)"
                )
                unused_raw_args.pop(raw_key, None)
                break

    return result


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def coerce_and_validate(
    tool_name: str,
    raw_args: dict[str, Any],
    schema: Type[ToolArgsModel] | None,
    aliases: AliasMap | None = None,
    mode: str = "permissive",
    request_id: str | None = None,
) -> ValidatedArgs:
    """
    Valida/corrige los args de una tool antes de ejecutarla.

    - Si `schema` es None (tool aún sin migrar a Pydantic): devuelve los
      args tal cual, sin tocar nada. Esto es lo que mantiene el sistema
      100% retrocompatible mientras se añaden esquemas tool por tool.
    - Si `mode == "strict"`: valida directamente con Pydantic, sin alias
      ni heurísticas. Cualquier campo extra o tipo incorrecto falla.
    - Si `mode == "permissive"` (default): aplica alias conocidos, ignora
      campos desconocidos, intenta rellenar campos obligatorios ausentes
      por similitud de nombre, y solo falla si después de todo eso el
      modelo sigue sin poder construirse.
    """

    logger = attach_request_id(tool_registry_logger, request_id)

    if schema is None:
        # Tool sin esquema registrado todavía: comportamiento de siempre.
        return ValidatedArgs(ok=True, args=dict(raw_args))

    if not isinstance(raw_args, dict):
        return ValidatedArgs(
            ok=False,
            error=f"Args de '{tool_name}' no son un objeto JSON válido: {raw_args!r}",
        )

    if mode == "strict":
        try:
            validated = schema(**raw_args)
            return ValidatedArgs(ok=True, args=validated.model_dump())
        except ValidationError as exc:
            return ValidatedArgs(
                ok=False,
                error=f"Args inválidos para '{tool_name}' (modo strict): {exc}",
            )

    # ---- modo permisivo ----
    warnings: list[str] = []
    aliases = aliases or {}

    mapped = _apply_aliases(raw_args, aliases)

    dropped = set(raw_args.keys()) - set(aliases.keys()) - set(schema.model_fields.keys())
    if dropped:
        warnings.append(
            f"campos desconocidos ignorados para '{tool_name}': {sorted(dropped)}"
        )

    try:
        validated = schema(**mapped)
        if warnings:
            logger.info("coerce_and_validate(%s): %s", tool_name, "; ".join(warnings))
        return ValidatedArgs(ok=True, args=validated.model_dump(), warnings=warnings)
    except ValidationError:
        pass

    # Último intento: rellenar campos obligatorios ausentes por heurística,
    # buscando entre TODAS las claves originales (cualquiera puede ser la
    # que el LLM quiso usar para el campo que falta).
    patched = _best_effort_fill(schema, mapped, dict(raw_args), warnings)

    try:
        validated = schema(**patched)
        logger.info(
            "coerce_and_validate(%s): recuperado tras heurística — %s",
            tool_name,
            "; ".join(warnings),
        )
        return ValidatedArgs(ok=True, args=validated.model_dump(), warnings=warnings)
    except ValidationError as exc:
        logger.warning(
            "coerce_and_validate(%s): no se pudo recuperar en modo permisivo: %s",
            tool_name,
            exc,
        )
        return ValidatedArgs(
            ok=False,
            warnings=warnings,
            error=f"Args inválidos para '{tool_name}': {exc}",
        )