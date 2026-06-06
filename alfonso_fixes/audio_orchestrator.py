#!/usr/bin/env python3
"""
audio_orchestrator.py — Fase 3

FIX: corregida importación de PlannerOrchestrator (anteriormente importaba
una clase 'Orchestrator' inexistente desde planner_orchestrator).
"""

import argparse
import asyncio
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.core.llm_client import OllamaClient
from app.core.planner_orchestrator import PlannerOrchestrator   # FIX
from app.tools.audio_tools import speech_to_text, text_to_speech, wake_word_listener

logger = logging.getLogger("audio_orchestrator")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


class AudioEnvironmentChecker:
    AUDIO_MODULES = ["sounddevice", "speech_recognition", "whisper", "edge_tts", "pyttsx3"]

    @staticmethod
    def _safe_import(name: str):
        try:
            module = importlib.import_module(name)
            return module, None
        except Exception as exc:
            return None, str(exc)

    @classmethod
    def check_modules(cls) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for module_name in cls.AUDIO_MODULES:
            module, error = cls._safe_import(module_name)
            result[module_name] = {
                "installed": module is not None,
                "error": error,
            }
        return result

    @classmethod
    def check_sounddevice(cls) -> Dict[str, Any]:
        module, error = cls._safe_import("sounddevice")
        if module is None:
            return {
                "available": False,
                "error": error,
                "devices": [],
                "default_input_device": None,
                "default_output_device": None,
                "device_count": 0,
            }

        try:
            devices = module.query_devices()
            default_input = None
            default_output = None
            try:
                default_device = module.default.device
                if default_device is None:
                    default_input = None
                    default_output = None
                elif hasattr(default_device, "input") and hasattr(default_device, "output"):
                    default_input = int(default_device.input) if default_device.input is not None else None
                    default_output = int(default_device.output) if default_device.output is not None else None
                elif isinstance(default_device, (tuple, list)) and len(default_device) == 2:
                    default_input = int(default_device[0]) if default_device[0] is not None else None
                    default_output = int(default_device[1]) if default_device[1] is not None else None
                elif isinstance(default_device, int):
                    default_input = default_output = default_device
                else:
                    default_input = default_output = str(default_device)
            except Exception:
                default_input = None
                default_output = None

            available = bool(devices)
            return {
                "available": available,
                "error": None if available else "No sound devices found",
                "devices": devices,
                "default_input_device": default_input,
                "default_output_device": default_output,
                "device_count": len(devices),
            }
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
                "devices": [],
                "default_input_device": None,
                "default_output_device": None,
                "device_count": 0,
            }

    @classmethod
    def check_tts_backends(cls) -> Dict[str, Any]:
        outcomes: Dict[str, Any] = {}
        for module_name in ["edge_tts", "pyttsx3"]:
            module, error = cls._safe_import(module_name)
            outcomes[module_name] = {
                "installed": module is not None,
                "error": error,
            }
        return outcomes

    @classmethod
    def run_all(cls) -> Dict[str, Any]:
        return {
            "modules": cls.check_modules(),
            "sounddevice": cls.check_sounddevice(),
            "tts_backends": cls.check_tts_backends(),
        }

    @classmethod
    async def run_audio_validation(cls, duration: int = 2, tts_text: str = "prueba de audio") -> Dict[str, Any]:
        report = cls.run_all()
        if not report["sounddevice"]["available"]:
            report["audio_validation"] = {"recorded": False, "message": "sounddevice no disponible"}
            return report

        try:
            stt_result = await speech_to_text(duration=duration)
            tts_result = await text_to_speech(tts_text)
            report["audio_validation"] = {
                "recorded": True,
                "stt_result": stt_result,
                "tts_result": tts_result,
            }
        except Exception as exc:
            report["audio_validation"] = {
                "recorded": False,
                "message": str(exc),
            }
        return report


class AudioOrchestrator:
    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url
        self.llm = OllamaClient()
        self.orchestrator = PlannerOrchestrator()   # FIX: clase correcta

    async def local_converse(
        self,
        keyword: str = "alfonso",
        wakeword_enabled: bool = True,
        max_duration: int = 30,
        chunk_duration: int = 5,
        stt_duration: int = 5,
        stt_model: str = "small",
        voice: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        wake_result = None
        if wakeword_enabled:
            logger.info("Escuchando wake word: %s", keyword)
            wake_result = await wake_word_listener(
                keyword=keyword,
                max_duration=max_duration,
                chunk_duration=chunk_duration,
                model=stt_model,
            )
            if wake_result.get("status") != "ok":
                return {"status": "error", "message": "Error en wake word", "wake_result": wake_result}
            if not wake_result.get("wake_word_detected"):
                return {"status": "ok", "message": "Wake word no detectada", "wake_result": wake_result}
            logger.info("Wake word detectada: %s", wake_result.get("text", ""))

        stt_result = await speech_to_text(duration=stt_duration, model=stt_model)
        if stt_result.get("status") != "ok":
            return {"status": "error", "message": "Error en STT", "stt_result": stt_result}

        user_text = stt_result.get("text", "").strip()
        if not user_text:
            return {"status": "error", "message": "No se detectó texto de voz", "stt_result": stt_result}

        logger.info("Texto detectado: %s", user_text)
        conversation_result = await self.orchestrator.run(
            user_text,
            self.llm,
            request_id=None,
            session_id=session_id,
        )

        if conversation_result.get("type") == "chat":
            response_text = conversation_result.get("response", "")
        else:
            response_text = str(conversation_result)

        tts_result = await text_to_speech(response_text, voice=voice)
        return {
            "status": "success",
            "wake_result": wake_result,
            "stt_result": stt_result,
            "conversation_result": conversation_result,
            "tts_result": tts_result,
        }

    def api_converse(self, base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = base_url.rstrip("/") + "/audio/converse"
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audio client y orquestador para el asistente")
    parser.add_argument("--mode", choices=["local", "api"], default="local")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--keyword", default="alfonso")
    parser.add_argument("--wakeword-enabled", action="store_true")
    parser.add_argument("--no-wakeword", dest="wakeword_enabled", action="store_false")
    parser.add_argument("--max-duration", type=int, default=30)
    parser.add_argument("--chunk-duration", type=int, default=5)
    parser.add_argument("--stt-duration", type=int, default=5)
    parser.add_argument("--stt-model", default="small")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audio-validation", action="store_true")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    checker = AudioEnvironmentChecker()

    if args.check:
        report = checker.run_all()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    if args.audio_validation:
        report = await checker.run_audio_validation(duration=args.stt_duration)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    orchestrator = AudioOrchestrator(api_url=args.api_url if args.mode == "api" else None)
    payload = {
        "keyword": args.keyword,
        "wakeword_enabled": args.wakeword_enabled,
        "max_duration": args.max_duration,
        "chunk_duration": args.chunk_duration,
        "stt_duration": args.stt_duration,
        "stt_model": args.stt_model,
        "voice": args.voice,
        "session_id": args.session_id,
    }

    if args.mode == "api":
        result = orchestrator.api_converse(args.api_url, payload)
    else:
        result = await orchestrator.local_converse(
            keyword=args.keyword,
            wakeword_enabled=args.wakeword_enabled,
            max_duration=args.max_duration,
            chunk_duration=args.chunk_duration,
            stt_duration=args.stt_duration,
            stt_model=args.stt_model,
            voice=args.voice,
            session_id=args.session_id,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupción del usuario")
        raise SystemExit(1)
