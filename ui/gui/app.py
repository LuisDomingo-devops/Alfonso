import sys
import os
import uuid
import numpy as np # Necesario para las funciones trigonométricas en la animación
import asyncio
import websockets
import json
import base64

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QWidget, QLabel, QFrame, QMessageBox, QPushButton, QLineEdit, QHBoxLayout, QScrollArea, QProgressBar)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent # Añadidos para la animación
from PyQt6.QtGui import QScreen, QPainter, QColor, QBrush, QPen, QPainterPath # Añadidos para el dibujo personalizado
from PyQt6 import uic

from core.api_client import AlfonsoAPI
from core.processor import ResponseProcessor
from services.audio import AudioService
from core.alfonso_agent_logic import AlfonsoAgentLogic


class AssistantThread(QThread):
    """Hilo secundario para el loop de escucha de voz."""
    new_message = pyqtSignal(str, str) # sender, message
    state_changed = pyqtSignal(str)    # idle, idle_text, listening, thinking, speaking
    # NEW: Signal for agent status (optional, but good for GUI feedback)
    agent_status_changed = pyqtSignal(str) # connected, disconnected, error
    audio_level_updated = pyqtSignal(int, str) # level, device_name

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.api = AlfonsoAPI(config['url']) if 'url' in config else AlfonsoAPI("http://localhost:8000")
        self.audio = AudioService()
        self.processor = ResponseProcessor()
        self.running = True
        self.session_id = str(uuid.uuid4())
        self.text_mode = False
        self.pending_text_message = None

        # NEW: Alfonso Agent Logic
        self.agent_logic = AlfonsoAgentLogic()
        self.bridge_url = config.get('bridge_url', "ws://localhost:8765") # Assuming bridge URL is passed in config
        self.websocket = None # To hold the WebSocket connection
        self.loop = None # asyncio event loop
        
        # Identificar el micrófono con "nombre y apellidos"
        self.device_name = "Dispositivo Predeterminado"
        device_id = config.get('device')
        if device_id is not None:
            for d in self.audio.list_input_devices():
                if d['index'] == device_id:
                    self.device_name = d['name']
                    break

    def set_text_mode(self, enabled: bool):
        """Cambia entre modo voz y modo texto."""
        self.text_mode = enabled
        self.state_changed.emit("idle_text" if enabled else "idle")

    def send_text_message(self, message: str):
        """Procesa un mensaje de texto (llamado desde la GUI)."""
        if not message.strip():
            return
        self.pending_text_message = message

    async def _audio_loop(self):
        """Loop de procesamiento de voz convertido a async."""
        keyword = self.config.get('keyword', 'alfonso').lower()
        device = self.config.get('device', None)
        output_device = self.config.get('output_device', None)

        # Handle threshold calibration for GUI mode
        threshold = self.config.get('threshold') # Get the raw value, which can be None
        if threshold is None:
            effective_device = device if device is not None else self.audio.device
            threshold = await asyncio.to_thread(self.audio.calibrate_threshold, effective_device)
            self.config['threshold'] = threshold # Update config for consistency

        while self.running:
            try:
                # MODO TEXTO
                if self.text_mode:
                    if self.pending_text_message:
                        user_text = self.pending_text_message
                        self.pending_text_message = None
                        
                        self.state_changed.emit("thinking")
                        self.new_message.emit("Tú", user_text)
                        
                        chat_res = self.api.send_chat(user_text, self.session_id)
                        response_data = chat_res.get("result", {})
                        response_text = self.processor.format_response(response_data)
                        self.new_message.emit("Alfonso", response_text)

                        audio_b64 = response_data.get("audio")
                        if audio_b64:
                            self.state_changed.emit("speaking")
                            audio_bytes = base64.b64decode(audio_b64)
                            await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                        else: # If server does not provide audio, use local TTS
                            if response_text: # Only speak if there's text to speak
                                self.state_changed.emit("speaking")
                                # Intentamos primero la voz humana (Edge-TTS)
                                audio_path = await self.audio.text_to_speech_human(response_text)
                                if audio_path:
                                    await asyncio.to_thread(self.audio.play_audio_file, audio_path)
                                else: # Fallback a voz robótica local si falla Edge-TTS
                                    audio_bytes = await asyncio.to_thread(self.audio.text_to_wav_bytes, response_text)
                                    if audio_bytes:
                                        await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                        
                        self.state_changed.emit("idle_text") # Vuelve a idle_text después de hablar
                    else:
                        self.msleep(100)
                    continue

                # Fase 1: Grabar chunk de audio (usamos to_thread para no bloquear el loop de comandos)
                wav = await asyncio.to_thread(self.audio.record_chunk, 3, device=device)
                
                # Emitir nivel de audio y nombre del micro para la GUI
                level = self.audio.get_level(wav)
                self.audio_level_updated.emit(level, self.device_name)

                if not self.audio.has_voice(wav, threshold):
                    # El log de volumen ahora sale desde audio.py para ser más preciso
                    continue

                print("[DEBUG] Voz detectada, verificando wake word...")
                # --- FASE 1.1: Detección de Wake Word local ---
                # Reemplazar la llamada a la API por una función local de detección de wake word
                # Por ahora, consideraremos cualquier voz detectada como una "wake word" basada en la actividad de voz.
                # Un modelo de wake word local más sofisticado (ej. Vosk, picovoice) se integraría aquí.
                # La variable `wakeword_text` se mantiene para compatibilidad con código posterior, pero estará vacía.
                wake_word_detected_locally = self.audio.has_voice(wav, threshold)
                wakeword_text = "" # No hay texto real de la detección local de wake word todavía
                if wake_word_detected_locally:
                    print(f"[OK] Wake word '{keyword}' detectada (mediante actividad de voz local).")
                    self.state_changed.emit("listening")
                    self.new_message.emit("Alfonso", "Dime, te escucho...")

                    await asyncio.sleep(0.3) # Tiempo de recuperación para el driver de audio

                    # Fase 2: Escuchar Orden (Grabamos 5s)
                    wav_order = await asyncio.to_thread(self.audio.record_chunk, 5, device=device)
                    
                    self.state_changed.emit("thinking")
                    
                    # --- FASE 2.1: Transcripción Local (Evita el 404) ---
                    print(f"\n[INFO] Procesando transcripción local...")
                    user_text = await asyncio.to_thread(self.audio.transcribe_local, wav_order)
                    
                    if user_text:
                        print(f"[OK] Alfonso ha entendido: '{user_text}'")
                        self.new_message.emit("Tú", user_text)
                        
                        # --- FASE 2.2: Envío al cerebro Alfonso (/chat) ---
                        # El payload enviado es: {"message": user_text, "session_id": self.session_id}
                        chat_res = await asyncio.to_thread(self.api.send_chat, user_text, self.session_id)
                        response_data = chat_res.get("result", {})
                        response_text = self.processor.format_response(response_data)
                        
                        self.new_message.emit("Alfonso", response_text)
                        
                        # --- FASE 2.2: Reproducción de Audio (TTS) ---
                        audio_b64 = response_data.get("audio")
                        if audio_b64:
                            self.state_changed.emit("speaking")
                            audio_bytes = base64.b64decode(audio_b64)
                            await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                        else: # If server does not provide audio, use local TTS
                            if response_text: # Only speak if there's text to speak
                                self.state_changed.emit("speaking")
                                audio_path = await self.audio.text_to_speech_human(response_text)
                                if audio_path:
                                    await asyncio.to_thread(self.audio.play_audio_file, audio_path)
                                else:
                                    audio_bytes = await asyncio.to_thread(self.audio.text_to_wav_bytes, response_text)
                                    if audio_bytes:
                                        await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                    else:
                        print("[WARN] El audio se procesó pero no se detectaron palabras.")
                        self.new_message.emit("Alfonso", "Lo siento, no te he oído bien.")
                    
                    print("[INFO] Volviendo a modo escucha (esperando wake word)...")
                    self.state_changed.emit("idle")

            except Exception as e:
                print(f"[ERROR] Error en el loop de audio: {e}")
                # En lugar de romper el loop (break), esperamos un poco e intentamos reconectar
                self.state_changed.emit("error")
                await asyncio.sleep(2)
                continue

    async def _agent_websocket_client_loop(self):
        """Connects to AlfonsoBridge and listens for commands."""
        while self.running:
            try:
                self.agent_status_changed.emit("connecting")
                async with websockets.connect(self.bridge_url) as ws:
                    self.websocket = ws
                    self.agent_status_changed.emit("connected")
                    print(f"[INFO] Conectado a Alfonso Bridge en {self.bridge_url}")
                    async for message in ws:
                        data = json.loads(message)
                        print(f"[INFO] Comando recibido del Bridge: {data}")
                        response = await self.agent_logic.execute_command(data)
                        await ws.send(json.dumps(response))
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
                print(f"[WARNING] Conexión a Alfonso Bridge perdida o rechazada: {e}. Reintentando en 5 segundos...")
                self.agent_status_changed.emit("disconnected")
                self.websocket = None
                await asyncio.sleep(5)
            except Exception as e:
                print(f"[ERROR] Error inesperado en el cliente del agente: {e}")
                self.agent_status_changed.emit("error")
                self.websocket = None
                await asyncio.sleep(5)

    def run(self):
        """Main entry point for the QThread, running the asyncio event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Initial backend connection check (can be blocking here or made async)
        self.state_changed.emit("connecting")
        print(f"[INFO] Intentando conectar al servidor backend: {self.api.base_url}")
        try:
            if not self.api.ping():
                print(f"[ERROR] No se pudo conectar al backend {self.api.base_url}. Revisa si el servidor está activo.")
                self.state_changed.emit("error")
                return
            print("[OK] Conexión con el servidor backend establecida.")
        except Exception as e:
            print(f"[CRITICAL] Error durante la conexión al backend: {e}")
            self.state_changed.emit("error")
            return

        self.state_changed.emit("idle")

        # Run both the audio loop and the agent WebSocket client loop concurrently
        try:
            self.loop.run_until_complete(asyncio.gather(self._audio_loop(), self._agent_websocket_client_loop()))
        except asyncio.CancelledError:
            print("[INFO] AssistantThread tasks cancelled.")
        finally:
            self.loop.close()
            print("[INFO] Asyncio event loop closed.")

    def stop(self):
        """Stops the running asyncio tasks and the event loop."""
        self.running = False
        if self.loop and self.loop.is_running():
            # Schedule tasks to be cancelled from the event loop thread
            self.loop.call_soon_threadsafe(lambda: [task.cancel() for task in asyncio.all_tasks(self.loop)])
            # The QThread.wait() will block until run() finishes.
        self.wait() # Wait for the QThread to finish its run() method

class AnimatedWaveWidget(QWidget):
    """
    Widget personalizado para mostrar una animación de onda/pulso
    que reacciona al estado del asistente.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(250, 250) # Reactor Core más grande y simétrico
        self._state = "idle"
        self._animation_phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_animation)
        self._timer.start(30) # Aproximadamente 30 FPS

        self._base_color = QColor(85, 85, 85) # Gris por defecto
        self._target_color = self._base_color
        self._current_color = self._base_color

        self._pulse_amplitude = 0 # Amplitud del pulso del círculo central
        self._wave_amplitude = 0  # Amplitud de la onda
        self._wave_frequency = 0  # Frecuencia de la onda
        self._wave_speed = 0      # Velocidad de desplazamiento de la onda

        self._color_animation = QPropertyAnimation(self, b"current_color")
        self._color_animation.setDuration(500)
        self._color_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def set_current_color(self, color: QColor):
        """Setter para la propiedad animada 'current_color'."""
        self._current_color = color
        self.update()

    def get_current_color(self) -> QColor:
        """Getter para la propiedad animada 'current_color'."""
        return self._current_color

    # Define current_color como una propiedad animable para QPropertyAnimation
    current_color = pyqtProperty(QColor, get_current_color, fset=set_current_color)

    def set_state(self, state: str):
        """Actualiza el estado del widget y ajusta la animación."""
        if self._state == state:
            return

        self._state = state
        self._animation_phase = 0.0 # Reiniciar fase de animación al cambiar de estado

        # Configuraciones de animación para cada estado
        state_configs = {
            "connecting": {"color": QColor(0, 255, 255), "pulse_amp": 5, "wave_amp": 10, "wave_freq": 0.05, "wave_speed": 0.05},
            "idle":       {"color": QColor(0, 150, 255, 150), "pulse_amp": 2, "wave_amp": 5, "wave_freq": 0.02, "wave_speed": 0.02},
            "idle_text":  {"color": QColor(100, 150, 255), "pulse_amp": 3, "wave_amp": 8, "wave_freq": 0.05, "wave_speed": 0.03},
            "listening":  {"color": QColor(0, 255, 255), "pulse_amp": 15, "wave_amp": 20, "wave_freq": 0.15, "wave_speed": 0.12},
            "thinking":   {"color": QColor(255, 0, 255), "pulse_amp": 8, "wave_amp": 30, "wave_freq": 0.08, "wave_speed": 0.05},
            "speaking":   {"color": QColor(0, 255, 150), "pulse_amp": 12, "wave_amp": 25, "wave_freq": 0.2, "wave_speed": 0.15},
            "error":      {"color": QColor(255, 50, 50), "pulse_amp": 0, "wave_amp": 0, "wave_freq": 0, "wave_speed": 0},
        }

        config = state_configs.get(state, state_configs["idle"])
        self._target_color = config["color"]
        self._pulse_amplitude = config["pulse_amp"]
        self._wave_amplitude = config["wave_amp"]
        self._wave_frequency = config["wave_freq"]
        self._wave_speed = config["wave_speed"]

        # Animar el cambio de color
        self._color_animation.stop()
        self._color_animation.setStartValue(self._current_color)
        self._color_animation.setEndValue(self._target_color)
        self._color_animation.start()

        if state == "error": # Detener animación en estado de error
            self._timer.stop()
        else:
            self._timer.start(30) # Reiniciar timer si no está en error

        self.update() # Forzar un repintado inicial

    def _update_animation(self):
        """Actualiza la fase de animación y repinta el widget."""
        self._animation_phase += self._wave_speed
        if self._animation_phase > 2 * np.pi: # Mantener la fase en un rango manejable
            self._animation_phase -= 2 * np.pi
        self.update()

    def paintEvent(self, event):
        """Método de pintado personalizado para dibujar la onda/pulso."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        
        # Color base con transparencia para efectos HUD
        base_color = self._current_color
        
        # 1. Anillo Exterior (Dashed/Segmentado)
        pen_outer = QPen(base_color, 1)
        pen_outer.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen_outer)
        outer_rect = int(min(width, height) * 0.8)
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(np.degrees(self._animation_phase * 0.5))
        painter.drawEllipse(int(-outer_rect/2), int(-outer_rect/2), outer_rect, outer_rect)
        painter.restore()

        # 2. Anillo de Datos (Círculos pequeños rotando)
        pen_data = QPen(base_color, 2)
        painter.setPen(pen_data)
        mid_rect = int(min(width, height) * 0.6)
        start_angle = int(np.degrees(self._animation_phase) * 16)
        span_angle = 60 * 16 # 60 grados
        painter.drawArc(int(center_x - mid_rect/2), int(center_y - mid_rect/2), 
                        mid_rect, mid_rect, start_angle, span_angle)
        painter.drawArc(int(center_x - mid_rect/2), int(center_y - mid_rect/2), 
                        mid_rect, mid_rect, start_angle + 180*16, span_angle)

        # 3. Núcleo Pulsante
        pulse_val = np.abs(np.sin(self._animation_phase * 2))
        core_size = int(20 + self._pulse_amplitude * pulse_val)
        
        # Brillo exterior del núcleo
        glow_color = QColor(base_color)
        glow_color.setAlpha(int(100 * pulse_val))
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(center_x - core_size), int(center_y - core_size), core_size*2, core_size*2)
        
        # Núcleo sólido
        painter.setBrush(QBrush(base_color))
        painter.drawEllipse(int(center_x - 10), int(center_y - 10), 20, 20)
        
        # 4. Líneas de Escaneo laterales (opcional, estilo HUD)
        if self._state in ["listening", "speaking"]:
            painter.setPen(QPen(base_color, 1))
            scan_y = int(center_y + self._wave_amplitude * np.sin(self._animation_phase * 3))
            painter.drawLine(int(center_x - outer_rect/2), scan_y, int(center_x + outer_rect/2), scan_y)


class ReactorWindow(QMainWindow):
    """Ventana independiente para el núcleo central (Reactor ARC)."""
    def __init__(self, config):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 300)

        self.container = QFrame(self)
        self.container.setObjectName("ReactorContainer")
        self.layout = QVBoxLayout(self.container)

        self.animated_wave = AnimatedWaveWidget()
        self.state_lbl = QLabel("STANDBY")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet("font-size: 10px; color: #00d1ff; text-transform: uppercase; font-weight: bold;")

        self.layout.addWidget(self.animated_wave, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.state_lbl)
        self.setCentralWidget(self.container)

    def update_visual_state(self, state):
        self.animated_wave.set_state(state)
        state_labels = {
            "connecting": "INICIALIZANDO", "idle": "STANDBY", "idle_text": "MODO TEXTO", 
            "listening": "ESCUCHANDO", "thinking": "PROCESANDO", "speaking": "TRANSMITIENDO", 
            "error": "ERROR CRÍTICO"
        }
        self.state_lbl.setText(state_labels.get(state, "OFFLINE"))
        
        border_colors = {
            "connecting": "#f1c40f", "idle": "#004466", "idle_text": "#6496ff", "listening": "#00d1ff",
            "thinking": "#bd00ff", "speaking": "#00ff85", "error": "#ff4b4b"
        }
        color = border_colors.get(state, "#004466")
        self.container.setStyleSheet(f"""
            #ReactorContainer {{
                background-color: rgba(5, 15, 25, 180);
                border-radius: 150px;
                border: 2px solid {color};
            }}
        """)


class AlfonsoGUI(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        

        # Cargar la interfaz diseñada en Qt Designer
        # uic.loadUi("gui/consola.ui", self)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Mantener fondo transparente
        self.setFixedSize(400, 400) # Tamaño optimizado para la consola de mensajes
        # La posición se gestionará en la función launch
        self.setFixedSize(400, 400)

        # Widget principal redondeado
        self.container = QFrame()
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet("""
            #MainContainer {
                background-color: rgba(5, 15, 25, 240);
                border-radius: 15px;
                border: 2px solid rgba(0, 200, 255, 80);
            }
            QLabel {
                color: #00d1ff;
                font-family: 'Consolas', 'Segoe UI', monospace;
                letter-spacing: 1px;
            }
            QLineEdit {
                background-color: rgba(50, 50, 50, 200);
                color: white;
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton {
                background-color: rgba(0, 209, 255, 30);
                color: #00d1ff;
                border: 1px solid #00d1ff;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton#ModeBtn {
                font-size: 9px;
            }
        """)
        
        main_layout = QVBoxLayout(self.container) # Usar main_layout para el contenedor principal
        # Área de Chat scrollable (Estilo HUD)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("ChatScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.viewport().setStyleSheet("background-color: #000000;")
        self.scroll_area.setStyleSheet("""
            #ChatScroll {
                background-color: #000000;
                border: 1px solid rgba(0, 255, 255, 30);
                border-radius: 10px;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(0, 255, 255, 10);
                width: 4px;
                margin: 0px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 255, 255, 150);
                min-height: 20px;
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)

        self.chat_lbl = QLabel("SISTEMA ALFONSO ONLINE\nEsperando wake word...")
        self.chat_lbl.setObjectName("ChatLabel")
        self.chat_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.chat_lbl.setWordWrap(True)
        self.chat_lbl.setContentsMargins(10, 10, 10, 10)
        self.chat_lbl.setStyleSheet("""
            #ChatLabel {
                font-size: 12px; 
                line-height: 1.4;
                color: #00ff00;
                background-color: #000000;
            }
        """)
        self.scroll_area.setWidget(self.chat_lbl)

        # Controles de modo texto
        mode_button_layout = QHBoxLayout()
        self.mode_button = QPushButton("TECLADO")
        self.mode_button.setObjectName("ModeBtn")
        self.mode_button.setMaximumWidth(100)
        self.mode_button.clicked.connect(self.toggle_text_mode)
        mode_button_layout.addStretch()
        mode_button_layout.addWidget(self.mode_button)
        mode_button_layout.addStretch()

        # Input de texto (inicialmente oculto)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Escribe tu mensaje aquí...")
        self.text_input.returnPressed.connect(self.send_text_message)
        self.text_input.setVisible(False)

        # VU Meter y nombre del micrófono
        self.vu_container = QVBoxLayout()
        self.mic_name_lbl = QLabel(f"MICRO: Buscando...")
        self.mic_name_lbl.setStyleSheet("font-size: 10px; color: rgba(0, 209, 255, 120); font-weight: bold;")
        self.mic_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.vu_meter = QProgressBar()
        self.vu_meter.setRange(0, 32768) # Rango máximo para audio de 16 bits
        self.vu_meter.setFixedHeight(4)
        self.vu_meter.setTextVisible(False)
        self.vu_meter.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0, 0, 0, 150);
                border: 1px solid rgba(0, 209, 255, 20);
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00ff00, stop:0.7 #ffff00, stop:1 #ff0000);
            }
        """)
        self.vu_container.addWidget(self.mic_name_lbl)
        self.vu_container.addWidget(self.vu_meter)

        # Botón de cierre provisional
        self.close_button = QPushButton("SHUTDOWN")
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 75, 75, 40);
                color: white;
                border: 1px solid #ff4b4b;
                font-size: 8px;
            }
        """)
        self.close_button.clicked.connect(self.close_gui)
        
        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(self.vu_container)
        main_layout.addLayout(mode_button_layout)
        main_layout.addWidget(self.text_input)
        main_layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.container)

        self.text_mode_enabled = False
        self.start_assistant()
        self.chat_history = "" # Historial acumulativo

    def toggle_text_mode(self):
        """Alterna entre modo voz y modo texto."""
        self.text_mode_enabled = not self.text_mode_enabled
        if self.text_mode_enabled:
            self.mode_button.setText("Modo Voz")
            self.text_input.setVisible(True)
            self.text_input.setFocus()
        else:
            self.mode_button.setText("Modo Texto")
            self.text_input.setVisible(False)
            self.text_input.clear()
        self.thread.set_text_mode(self.text_mode_enabled)

    def send_text_message(self):
        """Envía el mensaje de texto al hilo del asistente."""
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self.thread.send_text_message(text)

    def move_to_bottom_center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - 20
        self.move(x, y)

    def start_assistant(self):
        thread_config = self.config.copy()
        thread_config['bridge_url'] = self.config.get('bridge_url', "ws://localhost:8765")
        self.thread = AssistantThread(thread_config)
        self.thread.new_message.connect(self.update_chat)
        self.thread.state_changed.connect(self.update_visual_state)
        # NEW: Connect agent_status_changed signal
        self.thread.agent_status_changed.connect(self.update_agent_status)
        self.thread.audio_level_updated.connect(self.update_vu_meter)
        self.thread.start()

    def update_vu_meter(self, level, device_name):
        self.mic_name_lbl.setText(f"MIC: {device_name}")
        self.vu_meter.setValue(level)
    
    def close_gui(self):
        """Cierre ordenado del proceso."""
        if self.thread:
            self.thread.stop() # Call the new stop method
        os._exit(0) # Force exit after thread cleanup

    def update_chat(self, sender, text):
        color = "#00ff00" if sender == "Alfonso" else "#00ee00"
        new_entry = f"<p><b style='color:{color};'>[{sender.upper()}]</b><br>{text}</p>"
        self.chat_history += new_entry
        
        # Actualizar con todo el historial
        self.chat_lbl.setText(self.chat_history)
        
        # Auto-scroll al final (fondo) para ver el último mensaje
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum()))

    # NEW: Method to update agent status in GUI (e.g., in a status bar)
    def update_agent_status(self, status: str):
        print(f"[AGENT STATUS] {status}")
        # You could update a QLabel in the GUI here to show agent connection status
        # For example: self.agent_status_label.setText(f"Agente: {status}")

    def closeEvent(self, event):
        """Maneja el evento de cierre de la ventana."""
        if self.thread and self.thread.isRunning():
            reply = QMessageBox.question(self, 'Cerrar Alfonso',
                                         "¿Estás seguro de que quieres cerrar Alfonso?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.thread.stop()  # Call the new stop method
                event.accept()
            else:
                event.ignore()

    def update_visual_state(self, state):
        # El borde del contenedor principal también reacciona al estado
        border_colors = {
            "connecting": "#f1c40f", "idle": "#555", "idle_text": "#6496ff", "listening": "#00d1ff",
            "thinking": "#bd00ff", "speaking": "#00ff85", "error": "#ff4b4b"
        }
        border_color = border_colors.get(state, "#555")
        self.container.setStyleSheet(f"""
            #MainContainer {{
                background-color: rgba(5, 10, 20, 245);
                border-radius: 15px;
                border: 2px solid {border_color};
            }}
            QLabel {{ color: {border_color}; font-family: 'Segoe UI'; }}
            #ChatScroll, #ChatScroll > QWidget, #ChatScroll QWidget#qt_scrollarea_viewport {{ 
                background-color: #000000; 
            }}
            #ChatLabel {{ background-color: #000000; color: #00ff00; font-family: 'Consolas', 'Courier New', monospace; }}
            QLineEdit {{
                background-color: rgba(50, 50, 50, 200);
                color: white;
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 5px;
            }}
        """)

def launch(config):
    app = QApplication(sys.argv)
    console = AlfonsoGUI(config)
    reactor = ReactorWindow(config)
    
    # Conectar señales del hilo de la consola al reactor
    console.thread.state_changed.connect(reactor.update_visual_state)
    
    # Posicionamiento HUD
    screen = app.primaryScreen().availableGeometry()
    reactor.move((screen.width() - reactor.width()) // 2, screen.height() - reactor.height() - 50)
    # Consola a la izquierda del reactor
    console.move(reactor.x() - console.width() - 20, screen.height() - console.height() - 50)
    
    console.show()
    reactor.show()
    sys.exit(app.exec())