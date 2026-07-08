import sys
import os
import uuid
import numpy as np
import asyncio
import base64
import random
import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QWidget, QLabel, QFrame, QPushButton, QLineEdit, QHBoxLayout, QScrollArea, QProgressBar, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
                             QListWidget, QListWidgetItem, QTextEdit, QSplitter, QGroupBox, QDialog, QFormLayout, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent
from PyQt6.QtGui import QScreen, QPainter, QColor, QBrush, QPen, QPainterPath, QFont, QKeyEvent, QPixmap

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
    open_calendar = pyqtSignal()
    close_calendar = pyqtSignal()
    sync_calendar = pyqtSignal()
    open_mail = pyqtSignal()
    close_mail = pyqtSignal()
    sync_mail = pyqtSignal()
    open_editor = pyqtSignal()
    close_editor = pyqtSignal()


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

                        tools_to_trigger = []
                        if response_data.get("type") == "multi_tool":
                            for r in response_data.get("results", []):
                                if r.get("tool"):
                                    tools_to_trigger.append(r.get("tool"))
                        elif response_data.get("tool"):
                            tools_to_trigger.append(response_data.get("tool"))

                        for tool_name in tools_to_trigger:
                            if tool_name == "calendar_open_ui":
                                self.open_calendar.emit()
                            elif tool_name == "calendar_close_ui":
                                self.close_calendar.emit()
                            elif tool_name in ("calendar_create_event", "calendar_delete_event", "calendar_update_event"):
                                self.sync_calendar.emit()
                            elif tool_name == "mail_open_ui":
                                self.open_mail.emit()
                            elif tool_name == "mail_close_ui":
                                self.close_mail.emit()
                            elif tool_name in ("mail_receive_mock_emails", "mail_classify_emails", "mail_get_unread_summary"):
                                self.sync_mail.emit()
                            elif tool_name == "dev_studio_open_ui":
                                self.open_editor.emit()
                            elif tool_name == "dev_studio_close_ui":
                                self.close_editor.emit()
                        
                        if response_text and "[SISTEMA: Archivos guardados con éxito" in response_text:
                            self.open_editor.emit()

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

                        tools_to_trigger = []
                        if response_data.get("type") == "multi_tool":
                            for r in response_data.get("results", []):
                                if r.get("tool"):
                                    tools_to_trigger.append(r.get("tool"))
                        elif response_data.get("tool"):
                            tools_to_trigger.append(response_data.get("tool"))

                        for tool_name in tools_to_trigger:
                            if tool_name == "calendar_open_ui":
                                self.open_calendar.emit()
                            elif tool_name == "calendar_close_ui":
                                self.close_calendar.emit()
                            elif tool_name in ("calendar_create_event", "calendar_delete_event", "calendar_update_event"):
                                self.sync_calendar.emit()
                            elif tool_name == "mail_open_ui":
                                self.open_mail.emit()
                            elif tool_name == "mail_close_ui":
                                self.close_mail.emit()
                            elif tool_name in ("mail_receive_mock_emails", "mail_classify_emails", "mail_get_unread_summary"):
                                self.sync_mail.emit()
                            elif tool_name == "dev_studio_open_ui":
                                self.open_editor.emit()
                            elif tool_name == "dev_studio_close_ui":
                                self.close_editor.emit()
                        
                        if response_text and "[SISTEMA: Archivos guardados con éxito" in response_text:
                            self.open_editor.emit()
                        
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

        gui_dir = os.path.dirname(os.path.abspath(__file__))
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

    def _update_animation(self):
        self._animation_phase += 0.05
        if self._animation_phase > 1000.0:
            self._animation_phase = 0.0
        self.update()

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
        self.calendar_window = None
        self.mail_window = None
        self.editor_window = None
        
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
        self.tab_modules = QPushButton("CALENDARIO")
        self.tab_modules.clicked.connect(self.show_calendar)
        self.tab_mail = QPushButton("CORREO")
        self.tab_mail.clicked.connect(self.show_mail)
        self.tab_editor = QPushButton("DEV STUDIO")
        self.tab_editor.clicked.connect(self.show_editor)
        self.tab_diagnostics = QPushButton("DIAGNOSTICS")
        self.tab_logs = QPushButton("LOGS")
        self.tab_config = QPushButton("CONFIG")
        
        header_layout.addWidget(self.tab_dashboard)
        header_layout.addWidget(self.tab_modules)
        header_layout.addWidget(self.tab_mail)
        header_layout.addWidget(self.tab_editor)
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
        self.thread.open_calendar.connect(self.show_calendar)
        self.thread.close_calendar.connect(self.hide_calendar)
        self.thread.sync_calendar.connect(self.reload_calendar_events)
        self.thread.open_mail.connect(self.show_mail)
        self.thread.close_mail.connect(self.hide_mail)
        self.thread.sync_mail.connect(self.reload_mail_events)
        self.thread.open_editor.connect(self.show_editor)
        self.thread.close_editor.connect(self.hide_editor)
        self.thread.start()

    def hide_calendar(self):
        if self.calendar_window:
            self.calendar_window.close()

    def reload_calendar_events(self):
        if self.calendar_window and self.calendar_window.isVisible():
            self.calendar_window.load_events()

    def hide_mail(self):
        if self.mail_window:
            self.mail_window.close()

    def reload_mail_events(self):
        if self.mail_window and self.mail_window.isVisible():
            self.mail_window.load_emails()

    def show_mail(self):
        if not self.mail_window:
            self.mail_window = MailWidget(self.thread.api)
        self.mail_window.show()
        self.mail_window.raise_()
        self.mail_window.activateWindow()
        self.mail_window.load_emails()


    def show_calendar(self):
        if not self.calendar_window:
            self.calendar_window = CalendarWidget(self.thread.api)
        self.calendar_window.show()
        self.calendar_window.raise_()
        self.calendar_window.activateWindow()
        self.calendar_window.load_events()

    def hide_editor(self):
        if self.editor_window:
            self.editor_window.close()

    def show_editor(self):
        if not self.editor_window:
            from gui.editor_widget import DevEditorWidget
            self.editor_window = DevEditorWidget(self.thread.api)
        self.editor_window.show()
        self.editor_window.raise_()
        self.editor_window.activateWindow()
        self.editor_window.load_file_list()


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


class CalendarWidget(QWidget):
    """Interfaz gráfica nativa para el Calendario de Alfonso (MUTHUR OS)."""
    def __init__(self, api_client):
        super().__init__()
        self.api = api_client
        self.setWindowTitle("MUTHUR CALENDAR")
        self.setMinimumSize(850, 580)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        
        self.drag_position = None

        # Estilo retro hacker MUTHUR OS
        self.setStyleSheet("""
            QWidget {
                background-color: #030406;
                color: #00F0FF;
                font-family: 'Consolas', 'Roboto Mono', monospace;
            }
            QLabel {
                color: #00F0FF;
            }
            QPushButton {
                background-color: rgba(255, 184, 0, 15);
                color: #FFB800;
                border: 1px solid rgba(255, 184, 0, 50);
                border-radius: 3px;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Consolas';
            }
            QPushButton:hover {
                background-color: rgba(255, 184, 0, 40);
                color: #FFFFFF;
                border-color: #FFB800;
            }
            QPushButton:pressed {
                background-color: #FFB800;
                color: #000000;
            }
            QScrollArea {
                border: 1px solid rgba(255, 184, 0, 30);
                background-color: transparent;
            }
            QFrame#Separator {
                border: 1px solid rgba(255, 184, 0, 30);
            }
        """)

        # Fechas operativas
        now = datetime.datetime.now()
        self.current_year = now.year
        self.current_month = now.month
        self.selected_date = now.strftime("%Y-%m-%d")
        
        self.events_cache = {}  # YYYY-MM-DD -> list of event dicts

        self.setup_ui()
        self.load_events()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None

    def setup_ui(self):
        # Layout principal de la ventana
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)

        # Contenedor con borde completo MUTHUR OS
        container_frame = QFrame()
        container_frame.setObjectName("CalendarContainer")
        container_frame.setStyleSheet("""
            QFrame#CalendarContainer {
                border: 2px solid #FFB800;
                background-color: #030406;
            }
        """)
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(10)

        # ── CABECERA PERSONALIZADA (FRAMELESS HEADER) ──
        header_layout = QHBoxLayout()
        header_title = QLabel("// MUTHUR SYSTEMS // CALENDAR MODULE ver 1.2.0")
        header_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        
        btn_close_window = QPushButton("[X]")
        btn_close_window.setFixedWidth(40)
        btn_close_window.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #FFB800;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF4B4B;
                color: #FFFFFF;
            }
        """)
        btn_close_window.clicked.connect(self.close)

        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_close_window)
        container_layout.addLayout(header_layout)

        # Línea divisoria de cabecera
        header_sep = QFrame()
        header_sep.setFrameShape(QFrame.Shape.HLine)
        header_sep.setStyleSheet("background-color: rgba(255, 184, 0, 40); max-height: 1px; border: none;")
        container_layout.addWidget(header_sep)

        # Layout de contenido
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # ── PANEL IZQUIERDO: Calendario Mensual ──
        left_panel = QVBoxLayout()
        
        # Cabecera mes/año y navegación
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("< ANTERIOR")
        self.btn_prev.clicked.connect(self.prev_month)
        self.btn_next = QPushButton("SIGUIENTE >")
        self.btn_next.clicked.connect(self.next_month)
        
        self.month_label = QLabel("MES AÑO")
        self.month_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFB800;")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.month_label, 1)
        nav_layout.addWidget(self.btn_next)
        left_panel.addLayout(nav_layout)

        # Grid de días
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(5)
        
        # Cabecera de días de la semana
        days = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
        for idx, day in enumerate(days):
            lbl = QLabel(day)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-weight: bold; color: #FFB800; font-size: 11px; padding: 5px;")
            self.grid_layout.addWidget(lbl, 0, idx)

        # Botones de la cuadrícula de días (inicializar 6 filas x 7 columnas)
        self.day_buttons = []
        for r in range(6):
            row_buttons = []
            for c in range(7):
                btn = QPushButton("")
                btn.setFixedSize(55, 45)
                btn.setStyleSheet("font-size: 13px; font-weight: bold;")
                btn.clicked.connect(self.make_day_clicked_handler(r, c))
                self.grid_layout.addWidget(btn, r + 1, c)
                row_buttons.append(btn)
            self.day_buttons.append(row_buttons)

        left_panel.addLayout(self.grid_layout)
        left_panel.addStretch()
        content_layout.addLayout(left_panel, 3)

        # Línea divisoria
        divider = QFrame()
        divider.setObjectName("Separator")
        divider.setFrameShape(QFrame.Shape.VLine)
        content_layout.addWidget(divider)

        # ── PANEL DERECHO: Detalle de eventos ──
        right_panel = QVBoxLayout()
        
        self.details_header = QLabel("CITAS PARA EL DÍA")
        self.details_header.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFB800;")
        right_panel.addWidget(self.details_header)

        self.event_scroll = QScrollArea()
        self.event_scroll.setWidgetResizable(True)
        
        self.event_list_widget = QWidget()
        self.event_list_layout = QVBoxLayout(self.event_list_widget)
        self.event_list_layout.setContentsMargins(10, 10, 10, 10)
        self.event_list_layout.setSpacing(10)
        self.event_list_layout.addStretch()
        
        self.event_scroll.setWidget(self.event_list_widget)
        right_panel.addWidget(self.event_scroll)

        # Botón para cerrar
        self.btn_close = QPushButton("MINIMIZAR CALENDARIO")
        self.btn_close.clicked.connect(self.close)
        right_panel.addWidget(self.btn_close)

        content_layout.addLayout(right_panel, 2)
        container_layout.addLayout(content_layout)
        window_layout.addWidget(container_frame)

    def make_day_clicked_handler(self, row, col):
        return lambda: self.day_clicked(row, col)

    def prev_month(self):
        self.current_month -= 1
        if self.current_month < 1:
            self.current_month = 12
            self.current_year -= 1
        self.load_events()

    def next_month(self):
        self.current_month += 1
        if self.current_month > 12:
            self.current_month = 1
            self.current_year += 1
        self.load_events()

    def load_events(self):
        import calendar
        start_date = f"{self.current_year}-{self.current_month:02d}-01"
        last_day = calendar.monthrange(self.current_year, self.current_month)[1]
        end_date = f"{self.current_year}-{self.current_month:02d}-{last_day:02d}"

        self.events_cache.clear()
        res = self.api.get_calendar_events(start_date, end_date)
        if res.get("status") == "ok":
            for ev in res.get("events", []):
                dt = ev.get("start_time", "").split(" ")[0]
                if dt not in self.events_cache:
                    self.events_cache[dt] = []
                self.events_cache[dt].append(ev)

        self.draw_month()

    def draw_month(self):
        import calendar
        meses = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                 "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
        
        self.month_label.setText(f"{meses[self.current_month]} {self.current_year}")

        cal = calendar.Calendar(firstweekday=0)
        month_matrix = cal.monthdayscalendar(self.current_year, self.current_month)

        for r in range(6):
            for c in range(7):
                btn = self.day_buttons[r][c]
                
                btn.setEnabled(False)
                btn.setText("")
                btn.setStyleSheet("")
                btn.setProperty("day_val", 0)

                if r < len(month_matrix):
                    day_val = month_matrix[r][c]
                    if day_val > 0:
                        btn.setText(str(day_val))
                        btn.setEnabled(True)
                        btn.setProperty("day_val", day_val)
                        
                        date_str = f"{self.current_year}-{self.current_month:02d}-{day_val:02d}"
                        
                        has_events = date_str in self.events_cache
                        
                        if date_str == self.selected_date:
                            if has_events:
                                btn.setStyleSheet("background-color: #FFB800; color: #000000; border: 2px solid #00F0FF;")
                            else:
                                btn.setStyleSheet("background-color: #00F0FF; color: #000000; border: 1px solid #00F0FF;")
                        elif has_events:
                            btn.setStyleSheet("border: 2px solid #FFB800; color: #FFB800; background-color: rgba(255, 184, 0, 10);")
                        else:
                            btn.setStyleSheet("border: 1px solid rgba(0, 240, 255, 25); color: #00F0FF;")

    def day_clicked(self, row, col):
        btn = self.day_buttons[row][col]
        day_val = btn.property("day_val")
        if not day_val:
            return
            
        self.selected_date = f"{self.current_year}-{self.current_month:02d}-{day_val:02d}"
        self.draw_month()
        self.show_events_for_selected()

    def show_events_for_selected(self):
        while self.event_list_layout.count() > 1:
            item = self.event_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        try:
            dt_obj = datetime.datetime.strptime(self.selected_date, "%Y-%m-%d")
            dias_sem = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            self.details_header.setText(f"CITAS PARA EL {dias_sem[dt_obj.weekday()].upper()} {dt_obj.day}")
        except Exception:
            self.details_header.setText(f"CITAS DEL DÍA: {self.selected_date}")

        events = self.events_cache.get(self.selected_date, [])
        
        if not events:
            lbl = QLabel("NO HAY CITAS AGENDADAS PARA ESTE DÍA.")
            lbl.setStyleSheet("color: rgba(0, 240, 255, 60); font-style: italic; font-size: 11px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.event_list_layout.insertWidget(0, lbl)
            return

        for ev in events:
            frame = QFrame()
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 184, 0, 8);
                    border: 1px solid rgba(255, 184, 0, 30);
                    border-radius: 4px;
                    padding: 8px;
                }
            """)
            layout = QVBoxLayout(frame)
            layout.setSpacing(4)

            title = QLabel(f"★ {ev.get('title', 'Sin título').upper()}")
            title.setStyleSheet("font-weight: bold; color: #FFB800; font-size: 12px; border: none; background: transparent;")
            layout.addWidget(title)

            time_str = ev.get("start_time", "").split(" ")[1] if " " in ev.get("start_time", "") else ""
            end_str = ev.get("end_time", "").split(" ")[1] if ev.get("end_time") and " " in ev.get("end_time", "") else ""
            duration = f"HORA: {time_str}"
            if end_str:
                duration += f" - {end_str}"
            time_lbl = QLabel(duration)
            time_lbl.setStyleSheet("color: #00F0FF; font-size: 10px; border: none; background: transparent;")
            layout.addWidget(time_lbl)

            if ev.get("location"):
                loc_lbl = QLabel(f"LUGAR: {ev.get('location')}")
                loc_lbl.setStyleSheet("color: #FFFFFF; font-size: 10px; border: none; background: transparent;")
                layout.addWidget(loc_lbl)

            if ev.get("attendees"):
                att_lbl = QLabel(f"CON: {ev.get('attendees')}")
                att_lbl.setStyleSheet("color: #00FF66; font-size: 10px; border: none; background: transparent;")
                layout.addWidget(att_lbl)

            if ev.get("description"):
                desc_lbl = QLabel(f"NOTAS: {ev.get('description')}")
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet("color: rgba(255, 255, 255, 180); font-size: 10px; border: none; background: transparent;")
                layout.addWidget(desc_lbl)

            self.event_list_layout.insertWidget(self.event_list_layout.count() - 1, frame)



class EmailComposeDialog(QDialog):
    def __init__(self, parent, api_client, mode="compose", orig_email=None):
        super().__init__(parent)
        self.api = api_client
        self.mode = mode
        self.orig_email = orig_email
        self.setMinimumSize(500, 400)
        self.setWindowTitle("REDACATAR MENSAJE" if mode == "compose" else "RESPONDER MENSAJE" if mode == "reply" else "REENVIAR MENSAJE")
        
        # Estilo retro cyberpunk MUTHUR MAIL
        self.setStyleSheet("""
            QDialog {
                background-color: #030406;
                color: #00F0FF;
                border: 2px solid #FFB800;
            }
            QLabel {
                color: #FFB800;
                font-family: 'Consolas', monospace;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit, QTextEdit {
                background-color: #07090C;
                color: #FFFFFF;
                border: 1px solid rgba(255, 184, 0, 50);
                border-radius: 2px;
                padding: 6px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #00F0FF;
            }
            QPushButton {
                background-color: rgba(255, 184, 0, 15);
                color: #FFB800;
                border: 1px solid rgba(255, 184, 0, 50);
                border-radius: 3px;
                padding: 8px 16px;
                font-family: 'Consolas';
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 184, 0, 40);
                color: #FFFFFF;
                border-color: #FFB800;
            }
            QPushButton#SendBtn {
                background-color: rgba(0, 240, 255, 15);
                color: #00F0FF;
                border-color: rgba(0, 240, 255, 50);
            }
            QPushButton#SendBtn:hover {
                background-color: rgba(0, 240, 255, 40);
                border-color: #00F0FF;
                color: #FFFFFF;
            }
        """)
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.txt_recipient = QLineEdit()
        self.txt_subject = QLineEdit()
        self.txt_body = QTextEdit()
        
        form_layout.addRow("PARA:", self.txt_recipient)
        form_layout.addRow("ASUNTO:", self.txt_subject)
        form_layout.addRow("MENSAJE:", self.txt_body)
        
        layout.addLayout(form_layout)
        
        # Fila de botones
        btn_layout = QHBoxLayout()
        
        self.btn_draft = QPushButton("AUTO-REDACTAR CON ALFONSO")
        self.btn_draft.clicked.connect(self.generate_ai_draft)
        btn_layout.addWidget(self.btn_draft)
        
        btn_layout.addStretch()
        
        btn_send = QPushButton("ENVIAR")
        btn_send.setObjectName("SendBtn")
        btn_send.clicked.connect(self.send_email)
        btn_layout.addWidget(btn_send)
        
        btn_cancel = QPushButton("CANCELAR")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Pre-cargar datos si es respuesta o reenvío
        if self.orig_email:
            subj = self.orig_email.get("subject", "")
            if self.mode == "reply":
                self.txt_recipient.setText(self.orig_email.get("sender", ""))
                self.txt_subject.setText(f"Re: {subj}" if not subj.lower().startswith("re:") else subj)
            elif self.mode == "forward":
                self.txt_subject.setText(f"Fwd: {subj}" if not subj.lower().startswith("fwd:") else subj)
                self.txt_body.setText(f"\n\n---------- Mensaje reenviado ----------\nDe: {self.orig_email['sender']}\nFecha: {self.orig_email['received_at']}\nAsunto: {self.orig_email['subject']}\n\n{self.orig_email['body']}")
        else:
            self.btn_draft.setVisible(False)
            
    def generate_ai_draft(self):
        if not self.orig_email:
            return
        self.btn_draft.setText("GENERANDO...")
        self.btn_draft.setEnabled(False)
        QApplication.processEvents()
        
        res = self.api.get_reply_draft(self.orig_email["id"])
        
        self.btn_draft.setText("AUTO-REDACTAR CON ALFONSO")
        self.btn_draft.setEnabled(True)
        
        if res.get("status") == "ok":
            draft = res.get("draft", {})
            self.txt_body.setPlainText(draft.get("body", ""))
            role = res.get("role", "[Alfonso]")
            QMessageBox.information(self, "Borrador Generado", f"Borrador autoredactado con éxito por {role} basado en el contexto.")
        else:
            QMessageBox.warning(self, "Error", f"No se pudo autoredactar el borrador: {res.get('message', 'Error desconocido')}")
            
    def send_email(self):
        recipient = self.txt_recipient.text().strip()
        subject = self.txt_subject.text().strip()
        body = self.txt_body.toPlainText().strip()
        
        if not recipient or not subject or not body:
            QMessageBox.warning(self, "Error", "Por favor completa todos los campos.")
            return
            
        if self.mode == "compose":
            res = self.api.send_email(recipient, subject, body)
        elif self.mode == "reply":
            res = self.api.reply_email(self.orig_email["id"], body)
        elif self.mode == "forward":
            res = self.api.forward_email(self.orig_email["id"], recipient, body)
            
        if res.get("status") == "ok":
            QMessageBox.information(self, "Éxito", "Mensaje enviado correctamente.")
            self.accept()
        else:
            QMessageBox.warning(self, "Error al enviar", f"No se pudo enviar el correo: {res.get('message', 'Error desconocido')}")


class MailWidget(QWidget):
    """Interfaz gráfica nativa para el cliente de Correo Electrónico (MUTHUR MAIL)."""
    def __init__(self, api_client):
        super().__init__()
        self.api = api_client
        self.setWindowTitle("MUTHUR MAIL")
        self.setMinimumSize(950, 600)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        
        self.drag_position = None
        self.current_category = None  # None significa todos
        self.emails_list = []
        
        # Estilo retro hacker MUTHUR OS
        self.setStyleSheet("""
            QWidget {
                background-color: #030406;
                color: #00F0FF;
                font-family: 'Consolas', 'Roboto Mono', monospace;
            }
            QLabel {
                color: #00F0FF;
            }
            QPushButton {
                background-color: rgba(255, 184, 0, 15);
                color: #FFB800;
                border: 1px solid rgba(255, 184, 0, 50);
                border-radius: 3px;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Consolas';
            }
            QPushButton:hover {
                background-color: rgba(255, 184, 0, 40);
                color: #FFFFFF;
                border-color: #FFB800;
            }
            QPushButton:pressed {
                background-color: #FFB800;
                color: #000000;
            }
            QPushButton#CategoryBtn {
                background-color: rgba(0, 240, 255, 10);
                color: #00F0FF;
                border: 1px solid rgba(0, 240, 255, 30);
                text-align: left;
                padding-left: 12px;
            }
            QPushButton#CategoryBtn:hover {
                background-color: rgba(0, 240, 255, 30);
                border-color: #00F0FF;
                color: #FFFFFF;
            }
            QPushButton#CategoryBtn[active="true"] {
                background-color: #00F0FF;
                color: #000000;
                border: 1px solid #00F0FF;
                font-weight: bold;
            }
            QListWidget {
                border: 1px solid rgba(255, 184, 0, 30);
                background-color: rgba(5, 7, 10, 200);
                color: #FFFFFF;
            }
            QListWidget::item {
                border-bottom: 1px solid rgba(255, 184, 0, 15);
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 184, 0, 25);
                color: #FFFFFF;
                border: 1px solid #FFB800;
            }
            QScrollArea {
                border: 1px solid rgba(255, 184, 0, 30);
                background-color: transparent;
            }
            QFrame#Separator {
                border: 1px solid rgba(255, 184, 0, 30);
            }
        """)

        self.setup_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None

    def setup_ui(self):
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)

        # Contenedor con borde retro
        container_frame = QFrame()
        container_frame.setObjectName("MailContainer")
        container_frame.setStyleSheet("""
            QFrame#MailContainer {
                border: 2px solid #FFB800;
                background-color: #030406;
            }
        """)
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(10)

        # ── CABECERA DE LA VENTANA ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        header_title = QLabel("// MUTHUR SYSTEMS // MAIL CLIENT MODULE ver 1.0.0")
        header_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        header_layout.addWidget(header_title)
        
        header_layout.addStretch()
        
        btn_seed = QPushButton("INYECTAR MOCKS")
        btn_seed.clicked.connect(self.action_seed)
        header_layout.addWidget(btn_seed)
        
        self.btn_minimize = QPushButton("MINIMIZAR")
        self.btn_minimize.clicked.connect(self.close)
        header_layout.addWidget(self.btn_minimize)
        
        container_layout.addWidget(header_widget)

        # Separador horizontal
        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        container_layout.addWidget(sep)

        # ── CUERPO PRINCIPAL (Splitter de tres paneles) ──
        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setStyleSheet("QSplitter::handle { background-color: rgba(255, 184, 0, 30); }")

        # PANEL 1: CATEGORÍAS (Izquierda)
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)
        left_layout.setSpacing(8)

        lbl_cat = QLabel("CATEGORÍAS")
        lbl_cat.setStyleSheet("font-weight: bold; font-size: 10px; color: rgba(0, 240, 255, 70); margin-bottom: 4px;")
        left_layout.addWidget(lbl_cat)

        self.cat_buttons = {}
        categories = [
            ("TODOS", None),
            ("⚖ LEGAL", "legal"),
            ("📄 ADM.", "administrativo"),
            ("💼 EMPLEO", "empleo"),
            ("📢 COMERCIAL", "comercial"),
            ("✉ OTROS", "otros")
        ]
        for label, val in categories:
            btn = QPushButton(label)
            btn.setObjectName("CategoryBtn")
            btn.setProperty("cat_val", val)
            btn.clicked.connect(self.category_selected)
            self.cat_buttons[val] = btn
            left_layout.addWidget(btn)
        
        # Marcar "TODOS" como activo inicial
        self.cat_buttons[None].setProperty("active", "true")
        self.cat_buttons[None].setStyle(self.cat_buttons[None].style())

        left_layout.addStretch()
        body_splitter.addWidget(self.left_panel)

        # PANEL 2: LISTA DE CORREOS (Centro)
        self.center_panel = QWidget()
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setContentsMargins(5, 0, 5, 0)
        center_layout.setSpacing(8)

        inbox_header_layout = QHBoxLayout()
        lbl_inbox = QLabel("BANDEJA DE ENTRADA")
        lbl_inbox.setStyleSheet("font-weight: bold; font-size: 10px; color: rgba(0, 240, 255, 70);")
        inbox_header_layout.addWidget(lbl_inbox)
        inbox_header_layout.addStretch()
        
        btn_compose = QPushButton("REDACTAR (+)")
        btn_compose.setStyleSheet("font-size: 9px; font-weight: bold; padding: 4px 8px; max-height: 22px; max-width: 90px;")
        btn_compose.clicked.connect(self.action_compose)
        inbox_header_layout.addWidget(btn_compose)
        
        center_layout.addLayout(inbox_header_layout)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self.email_selected)
        center_layout.addWidget(self.list_widget)

        body_splitter.addWidget(self.center_panel)

        # PANEL 3: VISOR DE DETALLE (Derecha)
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(10)

        lbl_detail = QLabel("VISOR DE CORREO")
        lbl_detail.setStyleSheet("font-weight: bold; font-size: 10px; color: rgba(0, 240, 255, 70);")
        right_layout.addWidget(lbl_detail)
        
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)
        
        self.btn_reply = QPushButton("RESPONDER")
        self.btn_reply.clicked.connect(self.action_reply)
        self.btn_reply.setEnabled(False)
        
        self.btn_forward = QPushButton("REENVIAR")
        self.btn_forward.clicked.connect(self.action_forward)
        self.btn_forward.setEnabled(False)
        
        self.btn_delete = QPushButton("ELIMINAR")
        self.btn_delete.setStyleSheet("color: #FF0055; border-color: rgba(255, 0, 85, 40); background-color: rgba(255, 0, 85, 10);")
        self.btn_delete.clicked.connect(self.action_delete)
        self.btn_delete.setEnabled(False)
        
        actions_layout.addWidget(self.btn_reply)
        actions_layout.addWidget(self.btn_forward)
        actions_layout.addWidget(self.btn_delete)
        actions_layout.addStretch()
        
        right_layout.addLayout(actions_layout)

        # Recuadro con Scroll para ver el correo
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        scroll_content = QWidget()
        self.detail_layout = QVBoxLayout(scroll_content)
        self.detail_layout.setContentsMargins(12, 12, 12, 12)
        self.detail_layout.setSpacing(12)

        # Campos de metadatos
        self.lbl_sender = QLabel("De: --")
        self.lbl_sender.setStyleSheet("font-weight: bold; font-size: 12px; color: #FFFFFF;")
        self.detail_layout.addWidget(self.lbl_sender)

        self.lbl_subject = QLabel("Asunto: --")
        self.lbl_subject.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFB800;")
        self.lbl_subject.setWordWrap(True)
        self.detail_layout.addWidget(self.lbl_subject)

        self.lbl_date = QLabel("Fecha: --")
        self.lbl_date.setStyleSheet("font-size: 10px; color: rgba(0, 240, 255, 60);")
        self.detail_layout.addWidget(self.lbl_date)

        # Caja especial para el resumen de Alfonso
        self.summary_box = QFrame()
        self.summary_box.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 184, 0, 10);
                border: 1px solid rgba(255, 184, 0, 40);
                border-radius: 4px;
                padding: 10px;
            }
        """)
        summary_layout = QVBoxLayout(self.summary_box)
        summary_layout.setSpacing(4)
        
        summary_title = QLabel("✦ ALFONSO INTELLIGENT SUMMARY:")
        summary_title.setStyleSheet("font-weight: bold; font-size: 10px; color: #FFB800; border: none; background: transparent;")
        summary_layout.addWidget(summary_title)
        
        self.lbl_summary_text = QLabel("Selecciona un correo para ver el análisis de Alfonso.")
        self.lbl_summary_text.setWordWrap(True)
        self.lbl_summary_text.setStyleSheet("font-style: italic; color: #FFFFFF; font-size: 11px; border: none; background: transparent;")
        summary_layout.addWidget(self.lbl_summary_text)
        
        self.detail_layout.addWidget(self.summary_box)

        # Cuerpo del correo
        self.txt_body = QTextEdit()
        self.txt_body.setReadOnly(True)
        self.txt_body.setStyleSheet("border: none; background-color: transparent; color: #E0E0E0; font-size: 11px;")
        self.detail_layout.addWidget(self.txt_body)

        scroll_area.setWidget(scroll_content)
        right_layout.addWidget(scroll_area)

        body_splitter.addWidget(self.right_panel)

        # Ajuste de proporciones en el Splitter (15% izquierda, 40% centro, 45% derecha)
        body_splitter.setSizes([140, 380, 410])
        container_layout.addWidget(body_splitter)

        window_layout.addWidget(container_frame)

    def category_selected(self):
        sender_btn = self.sender()
        cat_val = sender_btn.property("cat_val")
        self.current_category = cat_val

        # Actualizar visual de botones activos
        for val, btn in self.cat_buttons.items():
            if val == cat_val:
                btn.setProperty("active", "true")
            else:
                btn.setProperty("active", "false")
            btn.setStyle(btn.style())

        self.load_emails()

    def action_seed(self):
        self.api.seed_emails()
        self.load_emails()

    def load_emails(self):
        self.list_widget.clear()
        self.emails_list = self.api.get_emails(category=self.current_category)
        
        if not self.emails_list:
            item = QListWidgetItem("Sin correos electrónicos en esta categoría.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list_widget.addItem(item)
            return

        for email in self.emails_list:
            subj = email.get("subject", "Sin asunto")
            sender = email.get("sender", "Desconocido")
            importance = email.get("importance", "Baja")
            read = email.get("read_status", 0)
            
            # Badge de importancia
            imp_badge = "[!]" if importance == "Alta" else "[ ]"
            
            # Estilo negrita si no está leído
            item_text = f"{imp_badge} {sender}\n      {subj}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, email)
            
            # Colorear según importancia
            if importance == "Alta":
                item.setForeground(QColor("#FF4B4B")) # Rojo
            elif read == 0:
                item.setForeground(QColor("#00F0FF")) # Cian brillante si no leído
            else:
                item.setForeground(QColor("#B0B0B0")) # Gris apagado si leído
                
            if read == 0:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                
            self.list_widget.addItem(item)

    def email_selected(self, current, previous):
        if not current:
            self.btn_reply.setEnabled(False)
            self.btn_forward.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        
        email = current.data(Qt.ItemDataRole.UserRole)
        if not email:
            self.btn_reply.setEnabled(False)
            self.btn_forward.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return

        self.btn_reply.setEnabled(True)
        self.btn_forward.setEnabled(True)
        self.btn_delete.setEnabled(True)

        # Rellenar campos del panel derecho
        self.lbl_sender.setText(f"De: {email.get('sender')}")
        self.lbl_subject.setText(f"Asunto: {email.get('subject')}")
        
        received = email.get("received_at", "")
        # Formatear fecha
        if received and len(received) > 16:
            received = received[:16].replace("T", " ")
        self.lbl_date.setText(f"Fecha: {received} | Categoría: {(email.get('category') or 'otros').upper()} | Importancia: {(email.get('importance') or 'Baja').upper()}")

        # Resumen corto de Alfonso
        summary = email.get("summary")
        if summary:
            self.lbl_summary_text.setText(summary)
        else:
            self.lbl_summary_text.setText("Este correo aún no ha sido clasificado por Alfonso. Haz click en clasificar o solicita el resumen de la mañana.")

        # Cuerpo del correo
        self.txt_body.setText(email.get("body", ""))

        # Marcar como leído en DB
        if email.get("read_status") == 0:
            self.api.mark_email_as_read(email.get("id"))
            # Recargar lista conservando selección para actualizar la negrita del item
            selected_id = email.get("id")
            self.load_emails()
            # Restaurar selección
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                item_data = item.data(Qt.ItemDataRole.UserRole)
                if item_data and item_data.get("id") == selected_id:
                    self.list_widget.setCurrentItem(item)
                    break

    def action_compose(self):
        dialog = EmailComposeDialog(self, self.api, mode="compose")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_emails()

    def action_reply(self):
        current = self.list_widget.currentItem()
        if not current:
            return
        email = current.data(Qt.ItemDataRole.UserRole)
        if not email:
            return
        dialog = EmailComposeDialog(self, self.api, mode="reply", orig_email=email)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_emails()

    def action_forward(self):
        current = self.list_widget.currentItem()
        if not current:
            return
        email = current.data(Qt.ItemDataRole.UserRole)
        if not email:
            return
        dialog = EmailComposeDialog(self, self.api, mode="forward", orig_email=email)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_emails()

    def action_delete(self):
        current = self.list_widget.currentItem()
        if not current:
            return
        email = current.data(Qt.ItemDataRole.UserRole)
        if not email:
            return
            
        reply = QMessageBox.question(
            self, 
            "Confirmar eliminación", 
            f"¿Estás seguro de que deseas eliminar permanentemente el correo:\n'{email.get('subject')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            res = self.api.delete_email(email.get("id"))
            if res.get("status") == "ok":
                QMessageBox.information(self, "Eliminado", "El correo ha sido eliminado correctamente.")
                self.lbl_sender.setText("De: --")
                self.lbl_subject.setText("Asunto: --")
                self.lbl_date.setText("Fecha: --")
                self.lbl_summary_text.setText("Selecciona un correo para ver el análisis de Alfonso.")
                self.txt_body.clear()
                self.btn_reply.setEnabled(False)
                self.btn_forward.setEnabled(False)
                self.btn_delete.setEnabled(False)
                self.load_emails()
            else:
                QMessageBox.warning(self, "Error", f"No se pudo eliminar el correo: {res.get('message', 'Error desconocido')}")



def launch(config):
    app = QApplication(sys.argv)
    dashboard = AlfonsoHUDDashboard(config)
    dashboard.show()
    sys.exit(app.exec())