"""
Suite de tests para cliente_voz.py

Cubre todas las funciones públicas y helpers en sus múltiples escenarios.
No requiere hardware de audio ni servidor real — todo se mockea.

Instalación:
    pip install pytest pytest-mock

Ejecución:
    pytest test_cliente_voz.py -v
    pytest test_cliente_voz.py -v -k "has_voice"      # solo tests de has_voice
    pytest test_cliente_voz.py -v --tb=short           # tracebacks cortos
"""

import io
import struct
import tempfile
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import pytest
import requests


# ---------------------------------------------------------------------------
# Importar funciones del cliente
# Las dependencias de hardware (sounddevice) se mockean a nivel de módulo
# ---------------------------------------------------------------------------

# Mockear sounddevice antes de importar el módulo cliente
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("sounddevice", MagicMock())
sys.modules.setdefault("pygame", MagicMock())

# Importar desde el fichero cliente.py (ajusta el nombre si es diferente)
import importlib.util
import os

_CLIENT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cliente.py")
_spec = importlib.util.spec_from_file_location("cliente", _CLIENT_FILE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Extraer funciones a testear
has_voice                   = _mod.has_voice
_ndarray_to_wav_bytes       = _mod._ndarray_to_wav_bytes
_extract_order_from_wakeword = _mod._extract_order_from_wakeword
_format_response            = _mod._format_response
ping_server                 = _mod.ping_server
detect_wake_word            = _mod.detect_wake_word
transcribe_audio            = _mod.transcribe_audio
send_chat                   = _mod.send_chat
get_tts                     = _mod.get_tts
list_input_devices          = _mod.list_input_devices
record_chunk                = _mod.record_chunk


# ---------------------------------------------------------------------------
# Helpers de test
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
CHANNELS    = 1

def _make_wav(amplitude: int = 1000, duration_s: float = 1.0) -> bytes:
    """Genera bytes WAV con señal de amplitud conocida."""
    n_samples = int(SAMPLE_RATE * duration_s)
    # Onda cuadrada simple con la amplitud pedida
    samples = np.full(n_samples, amplitude, dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _make_silence_wav(duration_s: float = 1.0) -> bytes:
    """Genera bytes WAV de silencio puro (amplitud 0)."""
    return _make_wav(amplitude=0, duration_s=duration_s)


def _make_low_noise_wav(duration_s: float = 1.0) -> bytes:
    """Genera WAV con ruido muy bajo (amplitud 10)."""
    return _make_wav(amplitude=10, duration_s=duration_s)


# ===========================================================================
# has_voice
# ===========================================================================

class TestHasVoice:

    def test_silencio_puro_devuelve_false(self):
        wav = _make_silence_wav()
        assert has_voice(wav, threshold=500) is False

    def test_voz_fuerte_devuelve_true(self):
        wav = _make_wav(amplitude=2000)
        assert has_voice(wav, threshold=500) is True

    def test_justo_en_el_umbral_devuelve_false(self):
        # Amplitud media == threshold → debe devolver False (no estrictamente mayor)
        wav = _make_wav(amplitude=500)
        assert has_voice(wav, threshold=500) is False

    def test_un_punto_sobre_el_umbral_devuelve_true(self):
        wav = _make_wav(amplitude=501)
        assert has_voice(wav, threshold=500) is True

    def test_umbral_cero_siempre_true_con_cualquier_señal(self):
        wav = _make_wav(amplitude=1)
        assert has_voice(wav, threshold=0) is True

    def test_umbral_muy_alto_siempre_false(self):
        wav = _make_wav(amplitude=1000)
        assert has_voice(wav, threshold=32767) is False

    def test_ruido_bajo_con_umbral_bajo_devuelve_true(self):
        wav = _make_low_noise_wav()
        assert has_voice(wav, threshold=5) is True

    def test_ruido_bajo_con_umbral_alto_devuelve_false(self):
        wav = _make_low_noise_wav()
        assert has_voice(wav, threshold=500) is False

    def test_threshold_por_defecto_es_500(self):
        # Voz por encima del default
        wav = _make_wav(amplitude=1000)
        assert has_voice(wav) is True

    def test_threshold_por_defecto_filtra_silencio(self):
        wav = _make_silence_wav()
        assert has_voice(wav) is False


# ===========================================================================
# _ndarray_to_wav_bytes
# ===========================================================================

class TestNdarrayToWavBytes:

    def test_devuelve_bytes(self):
        data = np.zeros(1000, dtype=np.int16)
        result = _ndarray_to_wav_bytes(data)
        assert isinstance(result, bytes)

    def test_cabecera_riff_valida(self):
        data = np.zeros(1000, dtype=np.int16)
        result = _ndarray_to_wav_bytes(data)
        assert result[:4] == b"RIFF"

    def test_se_puede_releer_como_wav(self):
        n = 1000
        data = np.full(n, 500, dtype=np.int16)
        wav_bytes = _ndarray_to_wav_bytes(data)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == SAMPLE_RATE
            assert wf.getnframes() == n

    def test_datos_se_preservan(self):
        data = np.array([100, 200, 300], dtype=np.int16)
        wav_bytes = _ndarray_to_wav_bytes(data)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        recovered = np.frombuffer(raw, dtype=np.int16)
        np.testing.assert_array_equal(data, recovered)

    def test_array_vacio(self):
        data = np.array([], dtype=np.int16)
        result = _ndarray_to_wav_bytes(data)
        assert isinstance(result, bytes)
        assert result[:4] == b"RIFF"

    def test_convierte_float_a_int16(self):
        # El método hace .astype(np.int16) internamente
        data = np.array([1.5, 2.7, 3.9], dtype=np.float32)
        result = _ndarray_to_wav_bytes(data)
        assert isinstance(result, bytes)


# ===========================================================================
# _extract_order_from_wakeword
# ===========================================================================

class TestExtractOrderFromWakeword:

    def test_solo_keyword_devuelve_none(self):
        assert _extract_order_from_wakeword("alfonso", "alfonso") is None

    def test_keyword_con_coma_y_orden(self):
        assert _extract_order_from_wakeword("alfonso, buenos días", "alfonso") == "buenos días"

    def test_keyword_con_espacio_y_orden(self):
        assert _extract_order_from_wakeword("alfonso buenos días", "alfonso") == "buenos días"

    def test_keyword_con_punto_final(self):
        # "alfonso." → None (solo la keyword con puntuación)
        assert _extract_order_from_wakeword("alfonso.", "alfonso") is None

    def test_keyword_mayusculas_se_normaliza(self):
        assert _extract_order_from_wakeword("Alfonso, qué hora es", "alfonso") == "qué hora es"

    def test_orden_larga(self):
        result = _extract_order_from_wakeword(
            "alfonso, crea un archivo llamado notas.txt con el contenido hola mundo",
            "alfonso"
        )
        assert result == "crea un archivo llamado notas.txt con el contenido hola mundo"

    def test_keyword_diferente(self):
        assert _extract_order_from_wakeword("jarvis, enciende la luz", "jarvis") == "enciende la luz"

    def test_texto_vacio_devuelve_none(self):
        assert _extract_order_from_wakeword("", "alfonso") is None

    def test_orden_solo_espacios_devuelve_none(self):
        # "alfonso,   " → la orden sería espacios → None
        assert _extract_order_from_wakeword("alfonso,   ", "alfonso") is None

    def test_keyword_no_al_principio_devuelve_none(self):
        # "di alfonso" → no empieza por keyword
        assert _extract_order_from_wakeword("di alfonso", "alfonso") is None


# ===========================================================================
# _format_response
# ===========================================================================

class TestFormatResponse:

    # --- tipo chat ---

    def test_chat_con_respuesta(self):
        data = {"type": "chat", "response": "Hola, ¿en qué puedo ayudarte?"}
        assert _format_response(data) == "Hola, ¿en qué puedo ayudarte?"

    def test_chat_sin_respuesta_devuelve_fallback(self):
        data = {"type": "chat"}
        assert _format_response(data) == "Sin respuesta."

    def test_chat_respuesta_vacia(self):
        data = {"type": "chat", "response": ""}
        assert _format_response(data) == "Sin respuesta."

    # --- tipo tool ---

    def test_tool_ok_con_mensaje(self):
        data = {
            "type": "tool",
            "tool": "create_file",
            "result": {"status": "ok", "message": "Archivo creado: /tmp/test.txt"}
        }
        assert _format_response(data) == "Archivo creado: /tmp/test.txt"

    def test_tool_ok_sin_mensaje(self):
        data = {
            "type": "tool",
            "tool": "system_info",
            "result": {"status": "ok"}
        }
        assert _format_response(data) == "Listo, ejecuté system_info correctamente."

    def test_tool_error(self):
        data = {
            "type": "tool",
            "tool": "run_command",
            "result": {"status": "error", "message": "Permiso denegado"}
        }
        result = _format_response(data)
        assert "run_command" in result
        assert "Permiso denegado" in result

    def test_tool_sin_nombre_usa_fallback(self):
        data = {
            "type": "tool",
            "result": {"status": "ok", "message": "Hecho"}
        }
        assert _format_response(data) == "Hecho"

    # --- tipo error ---

    def test_error_con_mensaje(self):
        data = {"type": "error", "message": "LLM no respondió"}
        assert _format_response(data) == "Error: LLM no respondió"

    def test_error_sin_mensaje(self):
        data = {"type": "error"}
        assert "error desconocido" in _format_response(data)

    # --- tipo desconocido ---

    def test_tipo_desconocido_devuelve_str(self):
        data = {"type": "unknown", "foo": "bar"}
        result = _format_response(data)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_dict_vacio(self):
        result = _format_response({})
        assert isinstance(result, str)


# ===========================================================================
# ping_server
# ===========================================================================

class TestPingServer:

    def test_servidor_responde_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("requests.get", return_value=mock_response):
            assert ping_server("http://localhost:8000") is True

    def test_servidor_responde_500(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        with patch("requests.get", return_value=mock_response):
            assert ping_server("http://localhost:8000") is False

    def test_servidor_responde_404(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch("requests.get", return_value=mock_response):
            assert ping_server("http://localhost:8000") is False

    def test_conexion_rechazada_devuelve_false(self):
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            assert ping_server("http://localhost:8000") is False

    def test_timeout_devuelve_false(self):
        with patch("requests.get", side_effect=requests.Timeout()):
            assert ping_server("http://localhost:8000") is False

    def test_url_invalida_devuelve_false(self):
        with patch("requests.get", side_effect=Exception("invalid URL")):
            assert ping_server("no-es-una-url") is False


# ===========================================================================
# detect_wake_word
# ===========================================================================

class TestDetectWakeWord:

    def _wav(self):
        return _make_wav(amplitude=1000)

    def test_detectada_devuelve_true(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "wake_word_detected": True, "text": "alfonso", "keyword": "alfonso"}
        }
        with patch("requests.post", return_value=mock_resp):
            result = detect_wake_word("http://localhost:8000", self._wav(), "alfonso")
        assert result["result"]["wake_word_detected"] is True

    def test_no_detectada_devuelve_false(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "wake_word_detected": False, "text": "hola mundo", "keyword": "alfonso"}
        }
        with patch("requests.post", return_value=mock_resp):
            result = detect_wake_word("http://localhost:8000", self._wav(), "alfonso")
        assert result["result"]["wake_word_detected"] is False

    def test_timeout_devuelve_error(self):
        with patch("requests.post", side_effect=requests.Timeout("timed out")):
            result = detect_wake_word("http://localhost:8000", self._wav(), "alfonso")
        assert result["status"] == "error"
        assert "timed out" in result["message"]

    def test_conexion_error_devuelve_error(self):
        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            result = detect_wake_word("http://localhost:8000", self._wav(), "alfonso")
        assert result["status"] == "error"

    def test_http_error_devuelve_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("requests.post", return_value=mock_resp):
            result = detect_wake_word("http://localhost:8000", self._wav(), "alfonso")
        assert result["status"] == "error"

    def test_keyword_personalizada_se_envia(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "wake_word_detected": True, "text": "jarvis", "keyword": "jarvis"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            detect_wake_word("http://localhost:8000", self._wav(), "jarvis", model="tiny")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["data"]["keyword"] == "jarvis"

    def test_modelo_se_envia_correctamente(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "wake_word_detected": False, "text": "", "keyword": "alfonso"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            detect_wake_word("http://localhost:8000", self._wav(), "alfonso", model="small")
        assert mock_post.call_args[1]["data"]["model"] == "small"


# ===========================================================================
# transcribe_audio
# ===========================================================================

class TestTranscribeAudio:

    def _wav(self):
        return _make_wav(amplitude=1000)

    def test_transcripcion_exitosa(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "text": "Buenos días Alfonso"}
        }
        with patch("requests.post", return_value=mock_resp):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["result"]["text"] == "Buenos días Alfonso"

    def test_texto_vacio_en_respuesta(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "text": ""}
        }
        with patch("requests.post", return_value=mock_resp):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["result"]["text"] == ""

    def test_timeout_devuelve_error(self):
        with patch("requests.post", side_effect=requests.Timeout()):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["status"] == "error"

    def test_conexion_error_devuelve_error(self):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["status"] == "error"

    def test_http_500_devuelve_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("requests.post", return_value=mock_resp):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["status"] == "error"

    def test_modelo_se_pasa_como_param(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "ok", "text": "test"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            transcribe_audio("http://localhost:8000", self._wav(), model="tiny")
        assert mock_post.call_args[1]["params"]["model"] == "tiny"

    def test_error_interno_del_servidor(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"status": "error", "message": "Whisper falló"}
        }
        with patch("requests.post", return_value=mock_resp):
            result = transcribe_audio("http://localhost:8000", self._wav())
        assert result["result"]["status"] == "error"


# ===========================================================================
# send_chat
# ===========================================================================

class TestSendChat:

    def test_respuesta_chat_normal(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"type": "chat", "response": "Hola, ¿en qué puedo ayudarte?"},
            "session_id": "abc123"
        }
        with patch("requests.post", return_value=mock_resp):
            result = send_chat("http://localhost:8000", "hola", "session-1")
        assert result["result"]["type"] == "chat"
        assert result["result"]["response"] == "Hola, ¿en qué puedo ayudarte?"

    def test_respuesta_tool(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {
                "type": "tool",
                "tool": "create_file",
                "result": {"status": "ok", "message": "Archivo creado"}
            }
        }
        with patch("requests.post", return_value=mock_resp):
            result = send_chat("http://localhost:8000", "crea un archivo", "session-1")
        assert result["result"]["type"] == "tool"

    def test_session_id_se_envia_en_header(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"type": "chat", "response": "ok"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            send_chat("http://localhost:8000", "hola", "mi-sesion-123")
        headers = mock_post.call_args[1]["headers"]
        assert headers["X-Session-ID"] == "mi-sesion-123"

    def test_mensaje_se_envia_en_body(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"type": "chat", "response": "ok"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            send_chat("http://localhost:8000", "buenos días", "session-1")
        body = mock_post.call_args[1]["json"]
        assert body["message"] == "buenos días"

    def test_timeout_devuelve_error(self):
        with patch("requests.post", side_effect=requests.Timeout()):
            result = send_chat("http://localhost:8000", "hola", "session-1")
        assert result["status"] == "error"

    def test_conexion_error_devuelve_error(self):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            result = send_chat("http://localhost:8000", "hola", "session-1")
        assert result["status"] == "error"

    def test_http_error_devuelve_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("422")
        with patch("requests.post", return_value=mock_resp):
            result = send_chat("http://localhost:8000", "", "session-1")
        assert result["status"] == "error"

    def test_mensaje_vacio_se_envia_igual(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "result": {"type": "chat", "response": "¿Dijiste algo?"}
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            send_chat("http://localhost:8000", "", "session-1")
        assert mock_post.call_args[1]["json"]["message"] == ""


# ===========================================================================
# get_tts
# ===========================================================================

class TestGetTts:

    def test_descarga_fichero_del_servidor(self, tmp_path):
        # El servidor devuelve una ruta y luego el fichero se descarga
        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {"audio_file": "/tmp/tts_abc.mp3"}
        }

        file_response = MagicMock()
        file_response.status_code = 200
        file_response.content = b"fake mp3 content"

        with patch("requests.post", return_value=tts_response):
            with patch("requests.get", return_value=file_response):
                result = get_tts("http://localhost:8000", "hola")

        assert result is not None
        assert result.endswith(".mp3")

    def test_usa_fichero_local_si_existe(self, tmp_path):
        # El fichero existe localmente (servidor en el mismo equipo)
        local_file = tmp_path / "tts_test.mp3"
        local_file.write_bytes(b"fake mp3")

        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {"audio_file": str(local_file)}
        }

        file_response = MagicMock()
        file_response.status_code = 404  # El endpoint de descarga no existe

        with patch("requests.post", return_value=tts_response):
            with patch("requests.get", return_value=file_response):
                result = get_tts("http://localhost:8000", "hola")

        assert result == str(local_file)

    def test_sin_audio_file_en_respuesta_devuelve_none(self):
        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {}
        }
        with patch("requests.post", return_value=tts_response):
            with patch("requests.get", return_value=MagicMock(status_code=404)):
                result = get_tts("http://localhost:8000", "hola")
        assert result is None

    def test_voz_personalizada_se_envia(self):
        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {"audio_file": "/tmp/tts.mp3"}
        }
        file_response = MagicMock()
        file_response.status_code = 200
        file_response.content = b"mp3"

        with patch("requests.post", return_value=tts_response) as mock_post:
            with patch("requests.get", return_value=file_response):
                get_tts("http://localhost:8000", "hola", voice="es-ES-ElviraNeural")

        payload = mock_post.call_args[1]["json"]
        assert payload["voice"] == "es-ES-ElviraNeural"

    def test_sin_voz_no_envia_campo_voice(self):
        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {"audio_file": "/tmp/tts.mp3"}
        }
        file_response = MagicMock()
        file_response.status_code = 200
        file_response.content = b"mp3"

        with patch("requests.post", return_value=tts_response) as mock_post:
            with patch("requests.get", return_value=file_response):
                get_tts("http://localhost:8000", "hola", voice=None)

        payload = mock_post.call_args[1]["json"]
        assert "voice" not in payload

    def test_excepcion_en_post_devuelve_none(self):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            result = get_tts("http://localhost:8000", "hola")
        assert result is None

    def test_excepcion_en_get_devuelve_none(self):
        tts_response = MagicMock()
        tts_response.json.return_value = {
            "status": "success",
            "result": {"audio_file": "/tmp/tts_inexistente.mp3"}
        }
        with patch("requests.post", return_value=tts_response):
            with patch("requests.get", side_effect=requests.ConnectionError()):
                result = get_tts("http://localhost:8000", "hola")
        assert result is None


# ===========================================================================
# list_input_devices
# ===========================================================================

class TestListInputDevices:

    def test_filtra_solo_dispositivos_de_entrada(self):
        fake_devices = [
            {"name": "Microphone A", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Speakers",     "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Headset",      "max_input_channels": 1, "max_output_channels": 1},
        ]
        with patch.object(_mod.sd, "query_devices", return_value=fake_devices):
            result = list_input_devices()
        names = [d["name"] for d in result]
        assert "Microphone A" in names
        assert "Headset" in names
        assert "Speakers" not in names

    def test_estructura_de_cada_dispositivo(self):
        fake_devices = [
            {"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
        ]
        with patch.object(_mod.sd, "query_devices", return_value=fake_devices):
            result = list_input_devices()
        assert len(result) == 1
        assert "index" in result[0]
        assert "name" in result[0]
        assert "channels" in result[0]
        assert result[0]["index"] == 0
        assert result[0]["name"] == "Mic"
        assert result[0]["channels"] == 1

    def test_sin_dispositivos_devuelve_lista_vacia(self):
        with patch.object(_mod.sd, "query_devices", return_value=[]):
            result = list_input_devices()
        assert result == []

    def test_indices_son_correctos(self):
        fake_devices = [
            {"name": "Output Only", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Mic 1",       "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Mic 2",       "max_input_channels": 2, "max_output_channels": 0},
        ]
        with patch.object(_mod.sd, "query_devices", return_value=fake_devices):
            result = list_input_devices()
        assert result[0]["index"] == 1  # "Output Only" (índice 0) está filtrado
        assert result[1]["index"] == 2


# ===========================================================================
# record_chunk
# ===========================================================================

class TestRecordChunk:

    def test_devuelve_bytes_wav(self):
        fake_recording = np.zeros((16000, 1), dtype=np.int16)
        with patch.object(_mod.sd, "rec", return_value=fake_recording):
            with patch.object(_mod.sd, "wait"):
                result = record_chunk(1)
        assert isinstance(result, bytes)
        assert result[:4] == b"RIFF"

    def test_duracion_se_pasa_a_sd_rec(self):
        fake_recording = np.zeros((32000, 1), dtype=np.int16)
        with patch.object(_mod.sd, "rec", return_value=fake_recording) as mock_rec:
            with patch.object(_mod.sd, "wait"):
                record_chunk(2)
        # 2 segundos × 16000 Hz = 32000 frames
        assert mock_rec.call_args[0][0] == 32000

    def test_device_none_no_pasa_kwarg(self):
        fake_recording = np.zeros((16000, 1), dtype=np.int16)
        with patch.object(_mod.sd, "rec", return_value=fake_recording) as mock_rec:
            with patch.object(_mod.sd, "wait"):
                record_chunk(1, device=None)
        assert "device" not in mock_rec.call_args[1]

    def test_device_especificado_se_pasa(self):
        fake_recording = np.zeros((16000, 1), dtype=np.int16)
        with patch.object(_mod.sd, "rec", return_value=fake_recording) as mock_rec:
            with patch.object(_mod.sd, "wait"):
                record_chunk(1, device=3)
        assert mock_rec.call_args[1].get("device") == 3

    def test_sd_wait_siempre_se_llama(self):
        fake_recording = np.zeros((16000, 1), dtype=np.int16)
        with patch.object(_mod.sd, "rec", return_value=fake_recording):
            with patch.object(_mod.sd, "wait") as mock_wait:
                record_chunk(1)
        mock_wait.assert_called_once()