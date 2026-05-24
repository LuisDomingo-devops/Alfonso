import json
from pathlib import Path
from unittest.mock import patch

from audio_orchestrator import AudioEnvironmentChecker


def test_audio_environment_checker_report_structure():
    report = AudioEnvironmentChecker.check_modules()

    assert isinstance(report, dict)
    assert "sounddevice" in report
    assert "speech_recognition" in report
    assert "whisper" in report
    assert "edge_tts" in report
    assert "pyttsx3" in report
    assert all("installed" in entry and "error" in entry for entry in report.values())


def test_audio_environment_checker_checks_sounddevice_with_missing_module():
    with patch("audio_orchestrator.importlib.import_module") as patched_import:
        def fake_import(name):
            if name == "sounddevice":
                raise ImportError("módulo no encontrado")
            return __import__(name)

        patched_import.side_effect = fake_import
        result = AudioEnvironmentChecker.check_sounddevice()

    assert result["available"] is False
    assert "error" in result
    assert result["devices"] == []


def test_audio_environment_checker_sounddevice_no_devices():
    class FakeSD:
        default = type("Default", (), {"device": (-1, -1)})

        @staticmethod
        def query_devices():
            return []

    with patch("audio_orchestrator.importlib.import_module") as patched_import:
        def fake_import(name):
            if name == "sounddevice":
                return FakeSD()
            return __import__(name)

        patched_import.side_effect = fake_import
        result = AudioEnvironmentChecker.check_sounddevice()

    assert result["available"] is False
    assert result["devices"] == []
    assert result["default_input_device"] == -1
    assert result["default_output_device"] == -1
    assert result["device_count"] == 0
