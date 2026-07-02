import sys
import os
import uuid
import numpy as np
import asyncio
import base64
import random
import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QWidget, QLabel, QFrame, QPushButton, QLineEdit, QHBoxLayout, QScrollArea, QProgressBar, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QMenu)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent
from PyQt6.QtGui import QScreen, QPainter, QColor, QBrush, QPen, QPainterPath, QFont, QKeyEvent

from core.api_client import AlfonsoAPI
from core.processor import ResponseProcessor
from services.audio import AudioService
from core.alfonso_agent_logic import AlfonsoAgentLogic


class AssistantThread(QThread):
    """Hilo secundario para el loop de escucha de voz."""
    new_message = pyqtSignal(str, str) # sender, message
    state_changed = pyqtSignal(str)    # idle, idle_text, listening, thinking, speaking
    agent_status_changed = pyqtSignal(str) # connected, disconnected, error
    audio_level_updated = pyqtSignal(int, str) # level, device_name

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.api = AlfonsoAPI(config['url']) if 'url' in config else AlfonsoAPI("http://localhost:8000")
        self.audio = AudioService()
        self.processor = ResponseProcessor()
        self.running = True
        # Obtener o crear Session ID persistente en ui/logs/session_config.json
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        ui_dir = os.path.dirname(gui_dir)
        logs_dir = os.path.join(ui_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        config_path = os.path.join(logs_dir, "session_config.json")
        
        session_id = None
        if os.path.exists(config_path):
            try:
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    session_id = json.load(f).get("session_id")
            except Exception:
                pass
        
        if not session_id:
            session_id = str(uuid.uuid4())
            try:
                import json
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump({"session_id": session_id}, f, indent=4)
            except Exception:
                pass
                
        self.session_id = session_id
        self.text_mode = False
        self.pending_text_message = None
        self.loop = None 
        
        self.device_name = "Dispositivo Predeterminado"
        device_id = config.get('device')
        if device_id is not None:
            for d in self.audio.list_input_devices():
                if d['index'] == device_id:
                    self.device_name = d['name']
                    break

    def set_text_mode(self, enabled: bool):
        self.text_mode = enabled
        self.state_changed.emit("idle_text" if enabled else "idle")

    def send_text_message(self, message: str):
        if not message.strip():
            return
        self.pending_text_message = message

    async def _audio_loop(self):
        keyword = self.config.get('keyword', 'alfonso').lower()
        device = self.config.get('device', None)
        output_device = self.config.get('output_device', None)

        threshold = self.config.get('threshold')
        if threshold is None:
            effective_device = device if device is not None else self.audio.device
            threshold = await asyncio.to_thread(self.audio.calibrate_threshold, effective_device)
            self.config['threshold'] = threshold 

        while self.running:
            try:
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
                        else:
                            if response_text:
                                self.state_changed.emit("speaking")
                                audio_path = await self.audio.text_to_speech_human(response_text)
                                if audio_path:
                                    await asyncio.to_thread(self.audio.play_audio_file, audio_path)
                                else:
                                    audio_bytes = await asyncio.to_thread(self.audio.text_to_wav_bytes, response_text)
                                    if audio_bytes:
                                        await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                        
                        self.state_changed.emit("idle_text")
                    else:
                        self.msleep(100)
                    continue

                wav = await asyncio.to_thread(self.audio.record_chunk, 3, device=device)
                level = self.audio.get_level(wav)
                self.audio_level_updated.emit(level, self.device_name)

                if not self.audio.has_voice(wav, threshold):
                    continue

                print("[DEBUG] Voz detectada, verificando wake word...")
                wake_word_detected_locally = self.audio.has_voice(wav, threshold)
                if wake_word_detected_locally:
                    print(f"[OK] Wake word '{keyword}' detectada (mediante actividad de voz local).")
                    self.state_changed.emit("listening")
                    self.new_message.emit("Alfonso", "Dime, te escucho...")

                    await asyncio.sleep(0.3)

                    wav_order = await asyncio.to_thread(self.audio.record_chunk, 5, device=device)
                    self.state_changed.emit("thinking")
                    
                    print(f"\n[INFO] Procesando transcripción local...")
                    user_text = await asyncio.to_thread(self.audio.transcribe_local, wav_order)
                    
                    if user_text:
                        print(f"[OK] Alfonso ha entendido: '{user_text}'")
                        self.new_message.emit("Tú", user_text)
                        
                        chat_res = await asyncio.to_thread(self.api.send_chat, user_text, self.session_id)
                        response_data = chat_res.get("result", {})
                        response_text = self.processor.format_response(response_data)
                        
                        self.new_message.emit("Alfonso", response_text)
                        
                        audio_b64 = response_data.get("audio")
                        if audio_b64:
                            self.state_changed.emit("speaking")
                            audio_bytes = base64.b64decode(audio_b64)
                            await asyncio.to_thread(self.audio.play_audio, audio_bytes, device=output_device)
                        else:
                            if response_text:
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
                self.state_changed.emit("error")
                await asyncio.sleep(2)
                continue

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

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

        try:
            self.loop.run_until_complete(self._audio_loop())
        except asyncio.CancelledError:
            print("[INFO] AssistantThread tasks cancelled.")
        finally:
            self.loop.close()
            print("[INFO] Asyncio event loop closed.")

    def stop(self):
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(lambda: [task.cancel() for task in asyncio.all_tasks(self.loop)])
        self.wait()


class HUDPanel(QFrame):
    """Contenedor visual estilo HUD con bordes iluminados y títulos retro (M.U.T.H.U.R.)."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.setObjectName("HUDPanel")
        self.setStyleSheet("""
            #HUDPanel {
                background-color: rgba(6, 8, 12, 230);
                border: 1px solid rgba(0, 240, 255, 30);
                border-radius: 4px;
            }
        """)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 35, 15, 15)
        
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Paleta de colores
        cyan = QColor(0, 240, 255, 120)
        amber = QColor(255, 184, 0, 220)
        
        # Título del panel
        font = QFont("Consolas", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(amber)
        painter.drawText(15, 22, self.title.upper())
        
        # Esquinas estilo HUD
        w, h = self.width(), self.height()
        painter.setPen(QPen(cyan, 2))
        length = 12
        # Superior Izquierda
        painter.drawLine(0, 0, length, 0)
        painter.drawLine(0, 0, 0, length)
        # Superior Derecha
        painter.drawLine(w, 0, w - length, 0)
        painter.drawLine(w, 0, w, length)
        # Inferior Izquierda
        painter.drawLine(0, h, length, h)
        painter.drawLine(0, h, 0, h - length)
        # Inferior Derecha
        painter.drawLine(w, h, w - length, h)
        painter.drawLine(w, h, w, h - length)


class AnimatedWaveWidget(QWidget):
    """Visualizador de rostro digital de Cain (Robocop 2) reactivo y animado."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self._state = "idle"
        self._animation_phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_animation)
        self._timer.start(30)

        self._raw_photo = QPixmap(os.path.join(gui_dir, "alfonso_photo.jpg"))
        self._processed_photo = None
        if not self._raw_photo.isNull():
            self._processed_photo = self._process_hologram_image(self._raw_photo)

        # Colores originales de los estados conservados exactamente
        self._base_color = QColor(255, 184, 0)
        self._target_color = self._base_color
        self._current_color = self._base_color

        self._color_animation = QPropertyAnimation(self, b"current_color")
        self._color_animation.setDuration(500)
        self._color_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def _process_hologram_image(self, raw_pixmap):
        from PyQt6.QtGui import QImage, QColor, QPainter, QBrush, QPixmap
        from PyQt6.QtCore import Qt, QSize
        import math
        
        # 1. Scale photo to a standard size for processing (e.g. 240x280)
        img = raw_pixmap.toImage().scaled(240, 280, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        
        # Crop tightly to center face
        cx_img = (img.width() - 200) // 2
        cy_img = (img.height() - 240) // 2
        img = img.copy(cx_img, cy_img, 200, 240)
        
        # Convert to ARGB32
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        
        # 2. Apply soft vignette to black (isolate the face)
        width, height = img.width(), img.height()
        mask_cx, mask_cy = width / 2.0, height / 2.0
        rx, ry = 85.0, 110.0 # Radios de la elipse facial
        
        for y in range(height):
            for x in range(width):
                col = QColor.fromRgb(img.pixel(x, y))
                
                # Factor de viñeta elíptica suave para fundir el borde de la foto a negro
                dx = (x - mask_cx) / rx
                dy = (y - mask_cy) / ry
                dist = math.sqrt(dx*dx + dy*dy)
                
                if dist >= 1.0:
                    alpha_factor = 0.0
                else:
                    # Atenuación coseno suave hacia los bordes
                    alpha_factor = math.cos(dist * math.pi / 2.0) ** 2
                
                # Multiplicar los componentes R, G, B por el factor de viñeta para fundir a negro puro
                r_final = int(col.red() * alpha_factor)
                g_final = int(col.green() * alpha_factor)
                b_final = int(col.blue() * alpha_factor)
                
                img.setPixel(x, y, QColor(r_final, g_final, b_final, col.alpha()).rgb())
        
        # 3. Generate the CRT Phosphor shadow mask pattern on top
        crt_mask = QImage(QSize(200, 240), QImage.Format.Format_ARGB32)
        crt_mask.fill(Qt.GlobalColor.transparent)
        
        m_painter = QPainter(crt_mask)
        m_painter.drawImage(0, 0, img)
        
        # Draw dense diagonal grid dots or fine lines to match the screen grid
        m_painter.setPen(QColor(0, 0, 0, 100)) # dark grid
        for y in range(0, 240, 2):
            offset = 1 if (y % 4 == 0) else 0
            for x in range(offset, 200, 2):
                m_painter.drawPoint(x, y)
                
        m_painter.end()
        
        return QPixmap.fromImage(crt_mask)

    def set_current_color(self, color: QColor):
        self._current_color = color
        self.update()

    def get_current_color(self) -> QColor:
        return self._current_color

    current_color = pyqtProperty(QColor, get_current_color, fset=set_current_color)

    def set_state(self, state: str):
        if self._state == state:
            return

        self._state = state
        self._animation_phase = 0.0

        # Mismo código de color original conservado exactamente
        state_configs = {
            "connecting": {"color": QColor(255, 184, 0)},
            "idle":       {"color": QColor(0, 191, 255, 150)},
            "idle_text":  {"color": QColor(0, 240, 255)},
            "listening":  {"color": QColor(0, 255, 102)},
            "thinking":   {"color": QColor(255, 100, 0)},
            "speaking":   {"color": QColor(0, 255, 240)},
            "error":      {"color": QColor(255, 50, 50)},
        }

        config = state_configs.get(state, state_configs["idle"])
        self._target_color = config["color"]

        self._color_animation.stop()
        self._color_animation.setStartValue(self._current_color)
        self._color_animation.setEndValue(self._target_color)
        self._color_animation.start()

        if state == "error":
            self._timer.start(30)
        else:
            self._timer.start(30)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        cx = width / 2
        cy = height / 2
        
        base_color = self._current_color
        
        # Jitter / glitch sutil para estados de procesamiento / error
        jitter_x = 0
        jitter_y = 0
        if self._state in ["thinking", "error"]:
            jitter_x = random.randint(-4, 4)
            jitter_y = random.randint(-4, 4)

        # Dibujar Cuadrícula de Fondo CRT
        painter.setPen(QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 15), 1))
        grid_size = 20
        for x in range(0, width, grid_size):
            painter.drawLine(x, 0, x, height)
        for y in range(0, height, grid_size):
            painter.drawLine(0, y, width, y)

        # Línea de barrido CRT
        scan_y = int((self._animation_phase / (2 * np.pi)) * height)
        painter.setPen(QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 75), 1.5))
        painter.drawLine(0, scan_y, width, scan_y)

        # --- DIBUJAR ROSTRO HOLOGRÁFICO PROCESADO ---
        if self._processed_photo and not self._processed_photo.isNull():
            # Dimensiones base del holograma centrado
            h_w, h_h = 200, 240
            rx = int(cx - h_w / 2 + jitter_x)
            ry = int(cy - h_h / 2 + jitter_y)
            
            # 1. Animación Orgánica Humana: Respiración (Sutil escala senoidal continua en IDLE)
            breath_scale_x = 1.0 + np.sin(self._animation_phase * 1.5) * 0.008
            breath_scale_y = 1.0 + np.cos(self._animation_phase * 1.5) * 0.005
            
            # 2. Animación Activa de Mandíbula/Mouth Warp al hablar (speaking)
            speak_warp = 0.0
            if self._state == "speaking":
                # Oscilación rápida simulando abrir/cerrar boca de manera natural
                speak_warp = np.abs(np.sin(self._animation_phase * 8.5)) * 0.08
                breath_scale_y += speak_warp
            
            final_w = int(h_w * breath_scale_x)
            final_h = int(h_h * breath_scale_y)
            rx = int(cx - final_w / 2 + jitter_x)
            ry = int(cy - final_h / 2 + jitter_y)
            
            # Dibujar la foto base procesada con las transformaciones de respiración/hablar
            # Para simular parpadeo de ojos real (Blinking) de forma holográfica
            # El ciclo senoidal rápido simula que cierra los párpados de vez en cuando
            is_blinking = False
            # Parpadeo periódico cada ~4 segundos
            cycle = int(self._animation_phase * 10) % 150
            if cycle in [140, 141, 142, 143]: # Parpadeo rápido (120ms)
                is_blinking = True

            # Modo Glitch para Thinking / Error: Cortar la imagen en tiras horizontales desplazadas
            if self._state in ["thinking", "error"] and random.random() < 0.35:
                segment_h = final_h // 5
                for i in range(5):
                    seg_y = ry + i * segment_h
                    seg_offset = random.choice([-8, -4, 4, 8]) if random.random() < 0.4 else 0
                    painter.drawPixmap(
                        rx + seg_offset, seg_y, final_w, segment_h,
                        self._processed_photo,
                        0, i * (240 // 5), 200, 240 // 5
                    )
            else:
                # Dibujo del holograma base
                painter.drawPixmap(rx, ry, final_w, final_h, self._processed_photo)
                
            # Sobredibujar efectos encima de la foto (Corte de ojos y boca en tiempo real)
            # A. Parpadeo de ojos (Blinking): Pone una sombra oscura sobre el área ocular de la foto
            if is_blinking:
                painter.save()
                # Ojos en el retrato (relativos al rectángulo dinámico rx, ry)
                eye_y = ry + int(final_h * 0.35)
                eye_h = int(final_h * 0.06)
                eye_l_x = rx + int(final_w * 0.34)
                eye_r_x = rx + int(final_w * 0.58)
                eye_w = int(final_w * 0.12)
                
                # Relleno del color de la sombra (simula párpados cerrados fundiéndose)
                painter.fillRect(eye_l_x, eye_y, eye_w, eye_h, QColor(0, 0, 0, 220))
                painter.fillRect(eye_r_x, eye_y, eye_w, eye_h, QColor(0, 0, 0, 220))
                painter.restore()
                
            # B. Vocalización de la boca (Mouth warp overlay):
            # Dibuja una sombra dinámica en los labios que se contrae y expande al hablar
            if self._state == "speaking" and speak_warp > 0.01:
                painter.save()
                # Posición de la boca aproximada en la imagen
                mouth_y = ry + int(final_h * 0.62)
                mouth_x = rx + int(final_w * 0.38)
                mouth_w = int(final_w * 0.24)
                mouth_h = int(final_h * 0.03 + speak_warp * 30) # Se estira al abrir
                
                # Hueco oscuro interno de la boca que se modula al hablar
                painter.fillRect(mouth_x + 4, mouth_y + 1, mouth_w - 8, mouth_h, QColor(0, 0, 0, 160))
                painter.restore()

            # C. Ondas de telemetría y escaneo sobre el rostro para enfatizar el estado activo
            if self._state == "listening":
                # Ondas concéntricas sutiles sobre los ojos (posicionados en el holograma)
                # Ojos aproximados: L=(cx-25), R=(cx+25), Y=(cy-15)
                painter.setPen(QPen(QColor(0, 255, 102, 100), 1))
                pulse = int((self._animation_phase * 12) % 30)
                painter.drawEllipse(int(cx - 25 + jitter_x - pulse/2), int(cy - 15 + jitter_y - pulse/2), pulse, pulse)
                painter.drawEllipse(int(cx + 25 + jitter_x - pulse/2), int(cy - 15 + jitter_y - pulse/2), pulse, pulse)
                
            elif self._state == "speaking":
                # Brillo de transmisión (Overlay translúcido fluctuante)
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                opacity = int(40 + np.abs(np.sin(self._animation_phase * 8.0)) * 60)
                painter.setOpacity(opacity / 255.0)
                painter.drawPixmap(rx, ry, final_w, final_h, self._processed_photo)
                painter.restore()
                
            elif self._state == "error":
                # Flashear tinte rojo sobre el error
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                painter.fillRect(rx, ry, final_w, final_h, QColor(255, 0, 0, 45))
                painter.restore()

            # E. Efecto de Ruido Estático VCR / Tracking analógico
            painter.save()
            # Línea de tracking VCR distorsionada horizontal
            track_y = ry + int(((self._animation_phase * 1.5) % 1.0) * final_h)
            painter.setPen(QPen(QColor(255, 255, 255, 60), 3))
            painter.drawLine(rx, track_y, rx + final_w, track_y)
            # Puntos de ruido estático VHS saltando aleatoriamente en el holograma
            painter.setPen(QPen(QColor(255, 255, 255, 120), 1.2))
            for _ in range(12):
                noise_x = random.randint(rx, rx + final_w)
                noise_y = random.randint(ry, ry + final_h)
                painter.drawPoint(noise_x, noise_y)
            painter.restore()

            # D. Marco / HUD de escaneo holográfico exterior
            painter.setPen(QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 140), 1))
            # Retículo exterior
            pad = 8
            painter.drawRect(rx - pad, ry - pad, h_w + pad*2, h_h + pad*2)
            # Indicadores de telemetría (esquinas resaltadas)
            painter.setPen(QPen(base_color, 2))
            len_hud = 15
            # Top-Left
            painter.drawLine(rx - pad, ry - pad, rx - pad + len_hud, ry - pad)
            painter.drawLine(rx - pad, ry - pad, rx - pad, ry - pad + len_hud)
            # Top-Right
            painter.drawLine(rx + h_w + pad, ry - pad, rx + h_w + pad - len_hud, ry - pad)
            painter.drawLine(rx + h_w + pad, ry - pad, rx + h_w + pad, ry - pad + len_hud)
            # Bot-Left
            painter.drawLine(rx - pad, ry + h_h + pad, rx - pad + len_hud, ry + h_h + pad)
            painter.drawLine(rx - pad, ry + h_h + pad, rx - pad, ry + h_h + pad - len_hud)
            # Bot-Right
            painter.drawLine(rx + h_w + pad, ry + h_h + pad, rx + h_w + pad - len_hud, ry + h_h + pad)
            painter.drawLine(rx + h_w + pad, ry + h_h + pad, rx + h_w + pad, ry + h_h + pad - len_hud)

class DataMatrixGrid(QWidget):
    """Cuadrícula 8x8 con animación parpadeante."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(160, 160)
        self.matrix = [[random.choice([0, 1]) for _ in range(8)] for _ in range(8)]
        self.colors = [QColor(15, 20, 25), QColor(0, 240, 255), QColor(255, 184, 0)]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_matrix)
        self.timer.start(250)

    def update_matrix(self):
        for i in range(8):
            for j in range(8):
                if random.random() < 0.25:
                    self.matrix[i][j] = random.choice([0, 1, 2])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        cell_w = self.width() / 8
        cell_h = self.height() / 8
        
        for i in range(8):
            for j in range(8):
                val = self.matrix[i][j]
                color = self.colors[val]
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor(0, 240, 255, 40), 1))
                x = i * cell_w + 1
                y = j * cell_h + 1
                painter.drawRect(int(x), int(y), int(cell_w - 2), int(cell_h - 2))


class CrtTerminalLabel(QLabel):
    """Label de texto con líneas CRT decorativas de fósforo/ámbar."""
    def __init__(self, text="", color_hex="#00FF66", parent=None):
        super().__init__(text, parent)
        self.color_hex = color_hex
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        pen = QPen(QColor(0, 0, 0, 45), 1)
        painter.setPen(pen)
        for y in range(0, self.height(), 3):
            painter.drawLine(0, y, self.width(), y)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            selected = self.selectedText()
            if selected:
                QApplication.clipboard().setText(selected)
                event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            font = self.font()
            size = font.pointSize()
            if size <= 0:
                size = font.pixelSize()
                if size <= 0:
                    size = 11
                new_size = max(8, min(48, size + (1 if delta > 0 else -1)))
                font.setPixelSize(new_size)
            else:
                new_size = max(8, min(48, size + (1 if delta > 0 else -1)))
                font.setPointSize(new_size)
            self.setFont(font)
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_action = menu.addAction("Copiar Selección")
        copy_action.setEnabled(self.hasSelectedText())
        action = menu.exec(event.globalPos())
        if action == copy_action:
            QApplication.clipboard().setText(self.selectedText())


class AlfonsoHUDDashboard(QMainWindow):
    """Dashboard consolidado MUTHUR SYSTEMS en pantalla completa."""
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("MUTHUR SYSTEMS ver 3.7.19")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen() 
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #030406;
            }
            QLabel {
                font-family: 'Consolas', 'Roboto Mono', monospace;
                font-size: 11px;
                color: #FFB800;
            }
            QPushButton {
                background-color: rgba(255, 184, 0, 15);
                color: #FFB800;
                border: 1px solid rgba(255, 184, 0, 50);
                border-radius: 3px;
                padding: 5px 12px;
                font-family: 'Consolas';
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 184, 0, 40);
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: #FFB800;
                color: #000000;
            }
            QLineEdit {
                background-color: rgba(10, 12, 16, 240);
                color: #FFFFFF;
                border: 1px solid rgba(0, 240, 255, 70);
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas';
                font-size: 12px;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(15)

        self.setup_header()
        self.setup_body_columns()
        self.setup_footer()

        # Carpeta de logs local para la UI y el Agente (ui/logs)
        self.ui_logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(self.ui_logs_dir, exist_ok=True)

        # Carpeta de logs del servidor (WSL / app)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.logs_dir = os.path.join(base_dir, 'logs')
        if not os.path.isdir(self.logs_dir):
            wsl_logs = r"\\wsl.localhost\Ubuntu\home\luisd\Alfonso\logs"
            if os.path.isdir(wsl_logs):
                self.logs_dir = wsl_logs
                
        self.current_log_file = "app.log"

        self.text_mode_enabled = False
        self.chat_history = ""
        self.uptime_seconds = 67472 
        
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_telemetry)
        self.ui_timer.start(1000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.read_logs)
        self.log_timer.start(1000)

        self.agent_process = None
        self.start_agent()
        self.start_assistant()

    def start_agent(self):
        try:
            import subprocess
            gui_dir = os.path.dirname(os.path.abspath(__file__))
            ui_dir = os.path.dirname(gui_dir)
            agent_path = os.path.join(ui_dir, "alfonso_agent.py")
            
            python_exe = sys.executable
            bridge_url = self.config.get('bridge_url', "ws://localhost:8765")
            
            # Limpiar agentes duplicados de forma no bloqueante usando psutil
            try:
                import psutil
                current_pid = os.getpid()
                for proc in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        cmdline = proc.info.get('cmdline')
                        if cmdline and any("alfonso_agent.py" in arg for arg in cmdline):
                            if proc.info.get('pid') != current_pid:
                                proc.terminate()
                    except Exception:
                        pass
            except Exception:
                pass

            creation_flags = 0
            if sys.platform == "win32":
                # CREATE_NO_WINDOW = 0x08000000
                creation_flags = 0x08000000
                
            self.agent_process = subprocess.Popen(
                [python_exe, agent_path, bridge_url],
                creationflags=creation_flags
            )
        except Exception as e:
            print(f"Error al iniciar el agente: {e}")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close_gui()
        super().keyPressEvent(event)

    def setup_header(self):
        header_layout = QHBoxLayout()
        
        logo_lbl = QLabel("MUTHUR SYSTEMS\nver 3.7.19")
        logo_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        header_layout.addWidget(logo_lbl)
        
        header_layout.addStretch()

        self.tab_dashboard = QPushButton("DASHBOARD")
        self.tab_dashboard.setStyleSheet("background-color: rgba(255, 184, 0, 40); border: 1px solid #FFB800; color: #FFFFFF;")
        self.tab_modules = QPushButton("MODULES")
        self.tab_diagnostics = QPushButton("DIAGNOSTICS")
        self.tab_logs = QPushButton("LOGS")
        self.tab_config = QPushButton("CONFIG")
        
        header_layout.addWidget(self.tab_dashboard)
        header_layout.addWidget(self.tab_modules)
        header_layout.addWidget(self.tab_diagnostics)
        header_layout.addWidget(self.tab_logs)
        header_layout.addWidget(self.tab_config)

        header_layout.addStretch()

        self.clock_lbl = QLabel("USER: ADMINISTRATOR   00:00:00\n00.00.0000")
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock_lbl.setStyleSheet("font-size: 12px; color: #00F0FF; font-weight: bold;")
        header_layout.addWidget(self.clock_lbl)

        self.main_layout.addLayout(header_layout)

    def setup_body_columns(self):
        body_layout = QHBoxLayout()
        body_layout.setSpacing(15)

        # COLUMNA IZQUIERDA
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)

        self.panel_status = HUDPanel("SYSTEM STATUS")
        status_vbox = QVBoxLayout()
        self.lbl_sys_id = QLabel("SYS. ID: MUTHUR-OS.3.7.19")
        self.lbl_core_temp = QLabel("CORE TEMP: 52.4 C")
        self.lbl_memory = QLabel("MEMORY: 68%")
        self.lbl_uptime = QLabel("UPTIME: 18:44:32")
        self.lbl_power = QLabel("POWER: NOMINAL")
        self.lbl_network = QLabel("NETWORK: SECURE")
        self.lbl_sys_load = QLabel("SYS. LOAD: 42%")
        self.lbl_operational = QLabel("\nALL SYSTEMS OPERATIONAL")
        self.lbl_operational.setStyleSheet("color: #00FF66; font-weight: bold;")
        
        for lbl in [self.lbl_sys_id, self.lbl_core_temp, self.lbl_memory, self.lbl_uptime, 
                    self.lbl_power, self.lbl_network, self.lbl_sys_load, self.lbl_operational]:
            status_vbox.addWidget(lbl)
        self.panel_status.main_layout.addLayout(status_vbox)
        left_layout.addWidget(self.panel_status, 1)

        self.panel_proc = HUDPanel("ACTIVE PROCESSES")
        self.proc_table = QTableWidget(7, 3)
        self.proc_table.setHorizontalHeaderLabels(["PID", "PROC_NAME", "STATUS"])
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
                gridline-color: rgba(0, 240, 255, 30);
                color: #00FF66;
                font-family: 'Consolas';
                font-size: 10px;
            }
            QHeaderView::section {
                background-color: rgba(255, 184, 0, 20);
                color: #FFB800;
                border: 1px solid rgba(0, 240, 255, 30);
                font-size: 9px;
            }
        """)
        processes = [
            ("2104", "CORE.DAEMON", "RUNNING"),
            ("2156", "NET.SERVICE", "RUNNING"),
            ("2258", "DB.WATCHER", "RUNNING"),
            ("2312", "IO.HANDLER", "RUNNING"),
            ("2458", "SECURITY.MOD", "RUNNING"),
            ("2596", "DIAG.MONITOR", "RUNNING"),
            ("2768", "LOG.WRITER", "RUNNING")
        ]
        for row, (pid, name, status) in enumerate(processes):
            self.proc_table.setItem(row, 0, QTableWidgetItem(pid))
            self.proc_table.setItem(row, 1, QTableWidgetItem(name))
            self.proc_table.setItem(row, 2, QTableWidgetItem(status))
        self.proc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.panel_proc.main_layout.addWidget(self.proc_table)
        left_layout.addWidget(self.panel_proc, 1)

        self.panel_logs = HUDPanel("LOG OUTPUT")
        log_ctrls = QHBoxLayout()
        self.btn_log_app = QPushButton("APP")
        self.btn_log_app.clicked.connect(lambda: self.change_log_file("app.log", self.btn_log_app))
        self.btn_log_agent = QPushButton("AGENT")
        self.btn_log_agent.clicked.connect(lambda: self.change_log_file("agent.log", self.btn_log_agent))
        self.btn_log_errors = QPushButton("ERRORS")
        self.btn_log_errors.clicked.connect(lambda: self.change_log_file("errors.log", self.btn_log_errors))
        log_ctrls.addWidget(self.btn_log_app)
        log_ctrls.addWidget(self.btn_log_agent)
        log_ctrls.addWidget(self.btn_log_errors)
        self.panel_logs.main_layout.addLayout(log_ctrls)

        self.log_scroll = QScrollArea()
        self.log_scroll.setWidgetResizable(True)
        self.log_scroll.viewport().setStyleSheet("background-color: #030406;")
        self.log_display = CrtTerminalLabel("INITIALIZING LOG SYSTEM...", color_hex="#FFB800")
        self.log_display.setWordWrap(True)
        self.log_display.setStyleSheet("font-family: 'Consolas'; font-size: 14px; color: #FFB800; background-color: #030406;")
        self.log_scroll.setWidget(self.log_display)
        self.panel_logs.main_layout.addWidget(self.log_scroll)

        body_layout.addLayout(left_layout, 1)

        # COLUMNA CENTRAL
        center_layout = QVBoxLayout()
        center_layout.setSpacing(15)

        self.panel_core = HUDPanel("CORE VISUALIZATION")
        self.animated_wave = AnimatedWaveWidget()
        self.panel_core.main_layout.addWidget(self.animated_wave, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.state_lbl = QLabel("STANDBY")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #00F0FF; letter-spacing: 2px;")
        self.panel_core.main_layout.addWidget(self.state_lbl)
        center_layout.addWidget(self.panel_core, 2)

        self.panel_chat = HUDPanel("CHAT CONSOLE / SIGNAL ANALYSIS")
        
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.viewport().setStyleSheet("background-color: #030406;")
        self.chat_lbl = CrtTerminalLabel("MUTHUR v4.2 ONLINE\nEsperando wake word...", color_hex="#00FF66")
        self.chat_lbl.setWordWrap(True)
        self.chat_lbl.setStyleSheet("font-family: 'Consolas'; font-size: 11px; color: #00FF66; background-color: #030406; line-height: 1.4;")
        self.chat_scroll.setWidget(self.chat_lbl)
        self.panel_chat.main_layout.addWidget(self.chat_scroll)

        chat_input_layout = QHBoxLayout()
        self.btn_mode = QPushButton("VOZ")
        self.btn_mode.clicked.connect(self.toggle_text_mode)
        self.btn_mode.setStyleSheet("min-width: 60px;")
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("INTRODUZCA ORDEN EN TERMINAL...")
        self.text_input.returnPressed.connect(self.send_text_message)
        
        chat_input_layout.addWidget(self.btn_mode)
        chat_input_layout.addWidget(self.text_input)
        self.panel_chat.main_layout.addLayout(chat_input_layout)

        center_layout.addWidget(self.panel_chat, 1)

        body_layout.addLayout(center_layout, 1)

        # COLUMNA DERECHA
        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)

        self.panel_scan = HUDPanel("SYSTEM SCAN / MIC INPUT")
        self.mic_name_lbl = QLabel("MIC: BUSCANDO DISPOSITIVO...")
        self.mic_name_lbl.setStyleSheet("font-size: 9px; color: #00F0FF;")
        self.vu_meter = QProgressBar()
        self.vu_meter.setRange(0, 32768)
        self.vu_meter.setFixedHeight(8)
        self.vu_meter.setTextVisible(False)
        self.vu_meter.setStyleSheet("""
            QProgressBar {
                background-color: rgba(5, 8, 12, 230);
                border: 1px solid rgba(0, 240, 255, 30);
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00FF66, stop:0.7 #FFB800, stop:1 #FF4B4B);
            }
        """)
        self.panel_scan.main_layout.addWidget(self.mic_name_lbl)
        self.panel_scan.main_layout.addWidget(self.vu_meter)
        right_layout.addWidget(self.panel_scan, 1)

        self.panel_matrix = HUDPanel("DATA MATRIX")
        self.matrix_widget = DataMatrixGrid()
        self.panel_matrix.main_layout.addWidget(self.matrix_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.panel_matrix, 2)

        self.panel_modules = HUDPanel("MODULE OVERVIEW")
        modules_layout = QGridLayout()
        modules_layout.setSpacing(10)
        
        mods = [
            ("CORE", "ONLINE", "#00FF66"),
            ("NETWORK", "ONLINE", "#00FF66"),
            ("SECURITY", "ONLINE", "#00FF66"),
            ("DATABASE", "ONLINE", "#00FF66"),
            ("I/O SYSTEMS", "NOMINAL", "#FFB800")
        ]
        for idx, (name, status, color) in enumerate(mods):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-weight: bold; color: #FFFFFF;")
            status_lbl = QLabel(status)
            status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            modules_layout.addWidget(name_lbl, idx, 0)
            modules_layout.addWidget(status_lbl, idx, 1)
            
        self.panel_modules.main_layout.addLayout(modules_layout)
        right_layout.addWidget(self.panel_modules, 2)

        self.panel_health = HUDPanel("SYSTEM HEALTH")
        health_layout = QHBoxLayout()
        self.health_bar = QProgressBar()
        self.health_bar.setRange(0, 100)
        self.health_bar.setValue(98)
        self.health_bar.setFixedHeight(12)
        self.health_bar.setTextVisible(False)
        self.health_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(5, 8, 12, 230);
                border: 1px solid rgba(0, 240, 255, 30);
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #00F0FF;
            }
        """)
        health_val_lbl = QLabel("98%")
        health_val_lbl.setStyleSheet("font-weight: bold; color: #00F0FF; font-size: 12px;")
        health_layout.addWidget(self.health_bar)
        health_layout.addWidget(health_val_lbl)
        self.panel_health.main_layout.addLayout(health_layout)
        right_layout.addWidget(self.panel_health, 1)

        body_layout.addLayout(right_layout, 1)

        body_layout.setStretch(0, 1)
        body_layout.setStretch(1, 1)
        body_layout.setStretch(2, 1)
        self.main_layout.addLayout(body_layout, 3)
        self.main_layout.addWidget(self.panel_logs, 1)

    def setup_footer(self):
        footer_layout = QHBoxLayout()

        self.alert_btn = QPushButton(" 2 ALERTS ")
        self.alert_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 75, 75, 25);
                color: #FF4B4B;
                border: 2px solid #FF4B4B;
                font-weight: bold;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background-color: #FF4B4B;
                color: #000000;
            }
        """)
        footer_layout.addWidget(self.alert_btn)
        
        footer_layout.addStretch()

        self.btn_minimize = QPushButton("MINIMIZE")
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 240, 255, 20);
                color: #00F0FF;
                border: 1px solid #00F0FF;
            }
            QPushButton:hover {
                background-color: #00F0FF;
                color: #000000;
            }
        """)
        self.btn_minimize.clicked.connect(self.showMinimized)
        footer_layout.addWidget(self.btn_minimize)

        self.btn_shutdown = QPushButton("SHUTDOWN SYSTEM")
        self.btn_shutdown.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 75, 75, 20);
                color: #FF4B4B;
                border: 1px solid #FF4B4B;
            }
            QPushButton:hover {
                background-color: #FF4B4B;
                color: #000000;
            }
        """)
        self.btn_shutdown.clicked.connect(self.close_gui)
        footer_layout.addWidget(self.btn_shutdown)

        self.main_layout.addLayout(footer_layout)

    def toggle_text_mode(self):
        self.text_mode_enabled = not self.text_mode_enabled
        if self.text_mode_enabled:
            self.btn_mode.setText("TECLADO")
            self.btn_mode.setStyleSheet("background-color: rgba(0, 240, 255, 30); color: #00F0FF; border: 1px solid #00F0FF;")
            self.text_input.setFocus()
        else:
            self.btn_mode.setText("VOZ")
            self.btn_mode.setStyleSheet("")
            self.text_input.clear()
        self.thread.set_text_mode(self.text_mode_enabled)

    def send_text_message(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            # Si el usuario envía texto pero está en modo VOZ, cambiar automáticamente a modo teclado/texto
            if not self.text_mode_enabled:
                self.toggle_text_mode()
            self.thread.send_text_message(text)

    def start_assistant(self):
        thread_config = self.config.copy()
        thread_config['bridge_url'] = self.config.get('bridge_url', "ws://localhost:8765")
        self.thread = AssistantThread(thread_config)
        self.thread.new_message.connect(self.update_chat)
        self.thread.state_changed.connect(self.update_visual_state)
        self.thread.audio_level_updated.connect(self.update_vu_meter)
        self.thread.start()

    def update_vu_meter(self, level, device_name):
        self.mic_name_lbl.setText(f"MIC: {device_name.upper()}")
        self.vu_meter.setValue(level)

    def update_chat(self, sender, text):
        color = "#00FF66" if sender == "Alfonso" else "#FFB800"
        new_entry = f"<p><b style='color:{color};'>[{sender.upper()}]</b><br>{text}</p>"
        self.chat_history += new_entry
        self.chat_lbl.setText(self.chat_history)
        QTimer.singleShot(50, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def update_visual_state(self, state):
        self.animated_wave.set_state(state)
        state_labels = {
            "connecting": "INICIALIZANDO OS", "idle": "STANDBY", "idle_text": "TECLADO ACTIVO", 
            "listening": "ESCUCHANDO...", "thinking": "PROCESANDO...", "speaking": "HABLANDO...", 
            "error": "ERROR CRITICO"
        }
        self.state_lbl.setText(state_labels.get(state, "OFFLINE"))
        
        state_colors = {
            "connecting": "#FFB800", "idle": "#00F0FF", "idle_text": "#00F0FF",
            "listening": "#00FF66", "thinking": "#FFB800", "speaking": "#00FF66", "error": "#FF4B4B"
        }
        self.state_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {state_colors.get(state, '#00F0FF')}; letter-spacing: 2px;")

    def change_log_file(self, filename, active_btn):
        self.current_log_file = filename
        self.log_display.setText(f"CARGANDO LOG: {filename.upper()}...")
        self.read_logs()

    def read_logs(self):
        logs_base = self.ui_logs_dir if self.current_log_file == "agent.log" else self.logs_dir
        filepath = os.path.join(logs_base, self.current_log_file)
        if not os.path.exists(filepath):
            self.log_display.setText(f"ERROR: ARCHIVO DE LOG NO ENCONTRADO\n{filepath}")
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-25:]
                content = "".join(last_lines)
                if not content.strip():
                    content = "ARCHIVO DE LOG VACÍO"
                self.log_display.setText(content)
                QTimer.singleShot(20, lambda: self.log_scroll.verticalScrollBar().setValue(self.log_scroll.verticalScrollBar().maximum()))
        except Exception as e:
            self.log_display.setText(f"ERROR AL LEER EL ARCHIVO:\n{str(e)}")

    def update_telemetry(self):
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%d.%m.%Y")
        self.clock_lbl.setText(f"USER: ADMINISTRATOR   {time_str}\n{date_str}")

        self.uptime_seconds += 1
        h = self.uptime_seconds // 3600
        m = (self.uptime_seconds % 3600) // 60
        s = self.uptime_seconds % 60
        self.lbl_uptime.setText(f"UPTIME: {h:02d}:{m:02d}:{s:02d}")

        temp = 52.4 + random.uniform(-0.5, 0.5)
        load = max(10, min(95, int(42 + random.uniform(-5, 5))))
        self.lbl_core_temp.setText(f"CORE TEMP: {temp:.1f} C")
        self.lbl_sys_load.setText(f"SYS. LOAD: {load}%")

    def close_gui(self):
        if self.thread:
            self.thread.stop()
        if hasattr(self, 'agent_process') and self.agent_process:
            try:
                self.agent_process.terminate()
                self.agent_process.wait(timeout=2)
            except Exception:
                pass
        os._exit(0)

    def closeEvent(self, event):
        self.close_gui()


def launch(config):
    app = QApplication(sys.argv)
    dashboard = AlfonsoHUDDashboard(config)
    dashboard.show()
    sys.exit(app.exec())