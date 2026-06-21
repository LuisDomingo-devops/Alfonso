from __future__ import annotations

import asyncio
import json
import re

from app.core.intent_router import IntentRouter
from app.core.llm_client import extract_json_robust
from app.core.memory import memory

from app.core.tool_registry import (
    get_tool,
    is_client_tool,
    get_client_action
)

from app.core.alfonso_bridge import bridge

from app.utils.logger import (
    attach_request_id,
    error_logger,
    orchestrator_logger
)


_router = IntentRouter()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_TOOL_TIMEOUT = 30


_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
    "create_file": "Archivo creado correctamente.",
    "delete_file": "Archivo eliminado."
}


FORCE_TOOL_KEYWORDS = [
    "abre",
    "open",
    "lanza",
    "ejecuta",
    "click",
    "escribe",
    "navega",
    "visita"
]


def _normalize_message(msg):
    return _TRAILING_PUNCT_RE.sub(
        "",
        msg.strip()
    )


def _force_tool(msg):

    msg = msg.lower()

    return any(
        x in msg
        for x in FORCE_TOOL_KEYWORDS
    )



def _extract_tool_and_args(data):

    if not isinstance(data, dict):
        return None,{}


    if "tool" in data:

        return (
            data["tool"],
            data.get("args", {})
        )


    key = next(iter(data),None)

    if key:

        value=data[key]

        if isinstance(value,dict):

            return (
                key,
                value.get("args",{})
            )


    return None,{}



class PlannerOrchestrator:


    def __init__(self,event_bus=None):
        self._bus=event_bus



    async def run(
        self,
        user_message,
        llm,
        request_id=None,
        session_id=None
    ):


        user_message=_normalize_message(
            user_message
        )


        logger=attach_request_id(
            orchestrator_logger,
            request_id
        )

        error=attach_request_id(
            error_logger,
            request_id
        )


        router=_router.detect_with_detail(
            user_message
        )


        if router["intent"]=="chat" and not _force_tool(user_message):


            result=await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id
            )


            return {
                "type":"chat",
                "response":result
            }



        raw=await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id
        )


        data=extract_json_robust(raw)


        if not data:

            return {
                "type":"error",
                "message":"JSON tool inválido",
                "raw":raw
            }



        tool_name,args=_extract_tool_and_args(
            data
        )


        if not tool_name:

            return {
                "type":"error",
                "message":"Tool desconocida"
            }



        #
        # CLIENTE
        #

        if is_client_tool(tool_name):


            action=get_client_action(
                tool_name
            )


            logger.info(
                "Enviando al cliente %s",
                action
            )


            result=await bridge.send_command(
                action,
                args
            )


            return {
                "type":"tool",
                "execution":"client",
                "tool":tool_name,
                "result":result
            }



        #
        # SERVIDOR
        #


        tool=get_tool(
            tool_name,
            request_id
        )


        if not tool:

            return {
                "type":"error",
                "message":
                f"No existe {tool_name}"
            }



        try:


            if asyncio.iscoroutinefunction(tool):

                result=await asyncio.wait_for(
                    tool(**args),
                    timeout=_TOOL_TIMEOUT
                )

            else:

                loop=asyncio.get_running_loop()

                result=await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: tool(**args)
                    ),
                    timeout=_TOOL_TIMEOUT
                )



        except Exception as e:

            error.exception(
                "Error tool"
            )

            return {
                "type":"error",
                "message":str(e)
            }



        if tool_name in _DIRECT_CONFIRM:

            return {
                "type":"chat",
                "response":
                _DIRECT_CONFIRM[tool_name]
            }



        return {
            "type":"tool",
            "execution":"server",
            "tool":tool_name,
            "result":result
        }