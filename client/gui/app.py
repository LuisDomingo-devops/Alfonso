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
                             QListWidget, QListWidgetItem, QTextEdit, QTextBrowser, QSplitter, QGroupBox, QDialog, QFormLayout, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent
from PyQt6.QtGui import QScreen, QPainter, QColor, QBrush, QPen, QPainterPath, QFont, QKeyEvent, QPixmap, QRadialGradient

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
    switch_session_requested = pyqtSignal(str, str, str) # session_id, project_name, title


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
            if hasattr(self.audio, 'calibrate_threshold'):
                threshold = await asyncio.to_thread(self.audio.calibrate_threshold, effective_device)
            else:
                # Fallback local seguro si la API de AudioService restaurada no lo expone
                from core.config import SILENCE_THRESHOLD
                threshold = SILENCE_THRESHOLD
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
                            elif tool_name == "switch_project_session":
                                # Cambiar la sesión activa de forma dinámica
                                p_data = response_data.get("args") or response_data.get("result", {})
                                if isinstance(p_data, dict):
                                    if "result" in p_data and isinstance(p_data["result"], dict):
                                        p_data = p_data["result"]
                                    new_sid = p_data.get("session_id")
                                    if new_sid:
                                        proj_name = p_data.get("project_name") or "default"
                                        title_name = p_data.get("title") or "Nueva conversación"
                                        self.switch_session_requested.emit(new_sid, proj_name, title_name)
                        
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
                            elif tool_name == "switch_project_session":
                                # Cambiar la sesión activa de forma dinámica
                                p_data = response_data.get("args") or response_data.get("result", {})
                                new_sid = p_data.get("session_id")
                                if new_sid:
                                    proj_name = p_data.get("project_name") or "default"
                                    title_name = p_data.get("title") or "Nueva conversación"
                                    self.switch_session_requested.emit(new_sid, proj_name, title_name)
                        
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
        self.wait(200)


class HUDPanel(QFrame):
    """Tarjeta contenedora estilo Glassmorphism Dark."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.setObjectName("HUDPanel")
        self.setStyleSheet("""
            #HUDPanel {
                background-color: rgba(20, 25, 35, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
        """)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 34, 16, 16)
        
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Punto de acento / Badge
        painter.setBrush(QBrush(QColor(0, 229, 255, 220)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(16, 17, 6, 6)
        
        # Título del panel
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(226, 232, 240, 220))
        painter.drawText(28, 23, self.title.upper())


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

    def _draw_ethereal_core(self, painter, cx, cy, base_color):
        import math
        t = self._animation_phase
        
        # Rotación 3D general del sistema orbital
        yaw = t * 0.4
        pitch = 0.65  # Inclinación fija elegante para perspectiva 3D
        roll = t * 0.15

        r, g, b = base_color.red(), base_color.green(), base_color.blue()

        # 1. Aura de Resplandor Radial de Fondo (Más pequeño)
        glow_grad = QRadialGradient(cx, cy, 90)
        glow_grad.setColorAt(0.0, QColor(r, g, b, 45))
        glow_grad.setColorAt(0.6, QColor(r, g, b, 12))
        glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - 100), int(cy - 100), 200, 200)

        painter.save()

        # Matriz de rotación 3D para proyectar círculos orbitales y partículas
        def project_3d_point(x, y, z):
            # Rotación Yaw (Eje Y)
            cos_y, sin_y = math.cos(yaw), math.sin(yaw)
            x1 = x * cos_y + z * sin_y
            z1 = -x * sin_y + z * cos_y
            
            # Rotación Pitch (Eje X)
            cos_p, sin_p = math.cos(pitch), math.sin(pitch)
            y2 = y * cos_p - z1 * sin_p
            z2 = y * sin_p + z1 * cos_p
            
            # Proyección perspectiva
            focal = 350.0
            dist = 280.0 + z2
            px = cx + (x1 * focal) / dist
            py = cy + (y2 * focal) / dist
            return px, py, z2

        # 2. Dibujar Anillos Concentricos en 3D (Radios Reducidos para Compactar)
        num_rings = 4
        base_radii = [24, 42, 60, 78]
        
        for idx, base_r in enumerate(base_radii):
            # Dinámica reactiva según el estado
            pulse = 0.0
            if self._state == "speaking":
                pulse = abs(math.sin(t * 9.0 - idx)) * 8.0
            elif self._state == "listening":
                pulse = math.sin(t * 4.0 + idx) * 3.5
            elif self._state == "thinking":
                pulse = math.sin(t * 8.0) * 2.0
            else: # idle
                pulse = math.sin(t * 1.5 + idx) * 1.8
                
            ring_r = base_r + pulse
            
            # Generar puntos del anillo 3D
            ring_pts = []
            steps = 48
            for step in range(steps):
                angle = (2.0 * math.pi * step) / steps
                # Cada anillo tiene una inclinación levemente cruzada para elegancia
                rx = ring_r * math.cos(angle)
                ry = ring_r * math.sin(angle)
                rz = math.sin(angle * 2.0) * 8.0
                
                px, py, pz = project_3d_point(rx, ry, rz)
                ring_pts.append((px, py, pz))
            
            # Dibujar trazado del anillo con modulación Z
            for i in range(steps):
                px1, py1, pz1 = ring_pts[i]
                px2, py2, pz2 = ring_pts[(i + 1) % steps]
                
                avg_z = (pz1 + pz2) / 2.0
                alpha = int(max(25, min(240, 140 + avg_z * 2.5)))
                
                pen = QPen(QColor(r, g, b, alpha), 1.1 if idx > 0 else 1.8)
                if idx == 1:
                    pen.setStyle(Qt.PenStyle.DashLine)
                elif idx == 2:
                    pen.setStyle(Qt.PenStyle.DotLine)
                    
                painter.setPen(pen)
                painter.drawLine(int(px1), int(py1), int(px2), int(py2))

        # 3. Nodos y Partículas Orbitantes en 3D (Constellation Field más compacto)
        num_particles = 16
        particle_pts = []
        for i in range(num_particles):
            # Órbitas cruzadas flotantes
            angle = (2.0 * math.pi * i) / num_particles + (t * 0.2)
            p_r = 52.0 + math.sin(t * 0.8 + i) * 7.0
            
            px = p_r * math.cos(angle)
            py = p_r * math.sin(angle)
            pz = math.cos(angle * 3.0) * 14.0
            
            px_p, py_p, pz_p = project_3d_point(px, py, pz)
            particle_pts.append((px_p, py_p, pz_p))

        # Dibujar líneas de constelación translúcidas
        for i in range(num_particles):
            px1, py1, pz1 = particle_pts[i]
            px2, py2, pz2 = particle_pts[(i + 1) % num_particles]
            
            avg_z = (pz1 + pz2) / 2.0
            alpha = int(max(10, min(100, 50 + avg_z * 1.5)))
            
            painter.setPen(QPen(QColor(r, g, b, alpha), 0.7))
            painter.drawLine(int(px1), int(py1), int(px2), int(py2))

        # Dibujar nodos de constelación brillantes
        for px_p, py_p, pz_p in particle_pts:
            alpha = int(max(40, min(255, 180 + pz_p * 3.0)))
            size = int(max(2, min(5, 3.5 + pz_p * 0.06)))
            
            painter.setBrush(QBrush(QColor(r, g, b, alpha)))
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.8)), 0.7))
            painter.drawEllipse(int(px_p - size/2), int(py_p - size/2), size, size)

        # 4. Núcleo Emisor Central (Reactor Core Glow - Más compacto)
        core_size = 12
        if self._state == "speaking":
            core_size += int(abs(math.sin(t * 12.0)) * 5)
        
        core_grad = QRadialGradient(cx, cy, core_size)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        core_grad.setColorAt(0.4, QColor(r, g, b, 230))
        core_grad.setColorAt(1.0, QColor(r, g, b, 0))
        painter.setBrush(QBrush(core_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - core_size), int(cy - core_size), core_size * 2, core_size * 2)

        # Ondas concéntricas de sonido al hablar
        if self._state == "speaking":
            for wave_idx in range(3):
                wave_r = 14 + ((t * 15 + wave_idx * 20) % 45)
                wave_alpha = int(max(0, 150 - (wave_r * 2.8)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(r, g, b, wave_alpha), 1.2))
                painter.drawEllipse(int(cx - wave_r), int(cy - wave_r), int(wave_r * 2), int(wave_r * 2))

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        cx = width / 2
        cy = height / 2
        
        base_color = self._current_color
        
        jitter_x = 0
        jitter_y = 0
        if self._state in ["thinking", "error"]:
            jitter_x = random.randint(-4, 4)
            jitter_y = random.randint(-4, 4)

        # 1. Dibujar Cuadrícula de Fondo CRT Estática
        painter.setPen(QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 12), 1))
        grid_size = 20
        for x in range(0, width, grid_size):
            painter.drawLine(x, 0, x, height)
        for y in range(0, height, grid_size):
            painter.drawLine(0, y, width, y)

        # 2. Dibujar Núcleo Orbital Holográfico Etereo en 3D
        self._draw_ethereal_core(painter, cx + jitter_x, cy + jitter_y, base_color)


class CrtTerminalLabel(QLabel):
    """Label de texto limpio para lecturas y logs sin parpadeo de barrido."""
    def __init__(self, text="", color_hex="#00FF66", parent=None):
        super().__init__(text, parent)
        self.color_hex = color_hex
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

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


class CrtTerminalTextBrowser(QTextBrowser):
    """TextBrowser moderno para renderizar Markdown con diseño Glassmorphism Dark."""
    def __init__(self, text="", color_hex="#00E5FF", parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #E2E8F0; line-height: 1.5;")
        self.setMarkdown(text)


class AlfonsoHUDDashboard(QMainWindow):
    """Dashboard consolidado ALFONSO OS en pantalla completa."""
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("ALFONSO OS ver 3.7.19")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen() 
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0B0E14;
            }
            QLabel {
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
                color: #CBD5E1;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 14px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton:pressed {
                background-color: #00E5FF;
                color: #0B0E14;
            }
            QTextEdit, QLineEdit {
                background-color: rgba(15, 20, 28, 0.9);
                color: #F8FAFC;
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 6px;
                padding: 8px 12px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QTextEdit:focus, QLineEdit:focus {
                border-color: #00E5FF;
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
        self.config_window = None
        self.diagnostics_window = None
        self.alerts_window = None
        
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
            
            from urllib.parse import urlparse
            server_url = self.config.get('url', 'http://localhost:8000')
            parsed = urlparse(server_url)
            host = parsed.hostname or "localhost"
            bridge_url = self.config.get('bridge_url', f"ws://{host}:8765")
            
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
        
        logo_lbl = QLabel("ALFONSO OS\nver 3.7.19")
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
        self.tab_diagnostics.clicked.connect(self.show_diagnostics)
        self.tab_logs = QPushButton("LOGS")
        self.tab_config = QPushButton("CONFIG")
        self.tab_config.clicked.connect(self.show_config)
        
        header_layout.addWidget(self.tab_dashboard)
        
        # Botón Proyectos (POP-UP) con el mismo estilo retro sci-fi
        self.btn_projects_popup = QPushButton("PROYECTOS")
        self.btn_projects_popup.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 240, 255, 0.05);
                color: #00F0FF;
                border: 1px solid rgba(0, 240, 255, 0.3);
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 240, 255, 0.2);
                border: 1px solid #00F0FF;
            }
        """)
        self.btn_projects_popup.clicked.connect(self.show_projects_navigator)
        header_layout.addWidget(self.btn_projects_popup)

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

        # COLUMNA IZQUIERDA (SIDEBAR: AVATAR + LOGS REALES)
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)

        # 1. Visualización de Rostro/Avatar
        self.panel_core = HUDPanel("CORE VISUALIZATION")
        self.animated_wave = AnimatedWaveWidget()
        self.panel_core.main_layout.addWidget(self.animated_wave, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.state_lbl = QLabel("STANDBY")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #00E5FF; letter-spacing: 2px;")
        self.panel_core.main_layout.addWidget(self.state_lbl)
        left_layout.addWidget(self.panel_core, 2)

        # 2. Salida de Logs en tiempo real
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
        self.log_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.log_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                background-color: rgba(15, 20, 28, 0.8);
            }
        """)
        self.log_scroll.viewport().setStyleSheet("background-color: transparent;")
        self.log_display = CrtTerminalLabel("INITIALIZING LOG SYSTEM...", color_hex="#10B981")
        self.log_display.setWordWrap(True)
        self.log_display.setStyleSheet("font-family: 'Consolas', 'Fira Code', monospace; font-size: 11px; color: #10B981; background-color: transparent; padding: 8px;")
        self.log_scroll.setWidget(self.log_display)
        self.panel_logs.main_layout.addWidget(self.log_scroll)
        left_layout.addWidget(self.panel_logs, 4)

        body_layout.addLayout(left_layout, 1)

        # COLUMNA DERECHA (PANTALLA DE CHAT EXPANDIDA)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)

        self.panel_chat = HUDPanel("CONVERSATION CONSOLE")
        
        # Etiqueta de sesión activa persistente
        self.lbl_active_session = QLabel("ACTIVO: NINGUNA SESIÓN CARGADA (Por favor abre un proyecto)")
        self.lbl_active_session.setStyleSheet("""
            font-family: 'Consolas', 'Fira Code', monospace;
            font-size: 11px;
            color: #FFB800;
            background-color: rgba(255, 184, 0, 0.05);
            border: 1px solid rgba(255, 184, 0, 0.2);
            border-radius: 4px;
            padding: 6px;
            margin-bottom: 5px;
        """)
        self.panel_chat.main_layout.addWidget(self.lbl_active_session)
        
        self.chat_lbl = CrtTerminalTextBrowser("ALFONSO v4.2 ONLINE\n\n*Inicialización completada. Esperando comandos de voz o selección de proyecto...*", color_hex="#00E5FF")
        self.panel_chat.main_layout.addWidget(self.chat_lbl, 1)

        chat_input_layout = QHBoxLayout()
        chat_input_layout.setSpacing(10)
        
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Escribe un mensaje para Alfonso...")
        self.text_input.setMaximumHeight(45)
        
        self.btn_send = QPushButton("ENVIAR")
        self.btn_send.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 229, 255, 0.1);
                color: #00E5FF;
                border: 1px solid #00E5FF;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00E5FF;
                color: #0B0E14;
            }
        """)
        self.btn_send.clicked.connect(self.send_text_message)
        
        # VU meter discreto integrado en la barra de control del chat
        self.mic_name_lbl = QLabel("MIC: BUSCANDO...")
        self.mic_name_lbl.setStyleSheet("font-size: 10px; color: #00E5FF; font-weight: bold;")
        self.vu_meter = QProgressBar()
        self.vu_meter.setRange(0, 100)
        self.vu_meter.setValue(0)
        self.vu_meter.setTextVisible(False)
        self.vu_meter.setFixedHeight(6)
        self.vu_meter.setFixedWidth(80)
        self.vu_meter.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 3px;
                background-color: rgba(15, 20, 28, 0.8);
            }
            QProgressBar::chunk {
                background-color: #00E5FF;
                border-radius: 2px;
            }
        """)
        
        # Botón para alternar teclado
        self.btn_mode = QPushButton("VOZ")
        self.btn_mode.setStyleSheet("background-color: rgba(0, 240, 255, 15); color: #00F0FF; border: 1px solid rgba(0, 240, 255, 0.3);")
        self.btn_mode.clicked.connect(self.toggle_text_mode)
        
        # Botón limpiar chat
        self.btn_clear = QPushButton("LIMPIAR")
        self.btn_clear.setStyleSheet("background-color: rgba(255, 255, 255, 0.05); color: #CBD5E1; border: 1px solid rgba(255, 255, 255, 0.1);")
        self.btn_clear.clicked.connect(self.clear_chat)
        
        chat_input_layout.addWidget(self.btn_mode)
        chat_input_layout.addWidget(self.btn_clear)
        chat_input_layout.addWidget(self.mic_name_lbl)
        chat_input_layout.addWidget(self.vu_meter)
        chat_input_layout.addWidget(self.text_input, 1)
        chat_input_layout.addWidget(self.btn_send)
        
        self.panel_chat.main_layout.addLayout(chat_input_layout)
        right_layout.addWidget(self.panel_chat, 1)

        body_layout.addLayout(right_layout, 3)
        self.main_layout.addLayout(body_layout, 1)

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
        self.alert_btn.clicked.connect(self.show_alerts)
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
        self.thread.set_text_mode(self.text_mode_enabled)

    def send_text_message(self):
        text = self.text_input.toPlainText().strip()
        if text:
            self.text_input.clear()
            # Si el usuario envía texto pero está en modo VOZ, cambiar automáticamente a modo teclado/texto
            if not self.text_mode_enabled:
                self.toggle_text_mode()
            self.thread.send_text_message(text)

    def clear_chat(self):
        self.chat_history = ""
        self.chat_lbl.setMarkdown("ALFONSO v4.2 ONLINE\n\n*Historial de conversación limpiado.*")

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
        self.thread.open_editor.connect(self.show_editor)
        self.thread.close_editor.connect(self.hide_editor)
        self.thread.switch_session_requested.connect(self.handler_switch_session)
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

    def hide_config(self):
        if self.config_window:
            self.config_window.close()

    def show_config(self):
        if not self.config_window:
            self.config_window = ConfigWidget(self)
        self.config_window.show()
        self.config_window.raise_()
        self.config_window.activateWindow()

    def show_projects_navigator(self):
        """Inicializa y abre el Pop-up flotante del listado de proyectos."""
        self.projects_dialog = ProjectNavigatorDialog(self)
        self.projects_dialog.show()
        self.projects_dialog.raise_()
        self.projects_dialog.activateWindow()
        # Rellenar datos en la ventana emergente recién creada
        self.reload_projects_list()

    def handler_switch_session(self, session_id, project_name, title):
        """Manejador ejecutado de forma segura en el hilo principal para aplicar el cambio de proyecto."""
        self.thread.session_id = session_id
        
        # Guardar persistencia local de sesión
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(os.path.dirname(gui_dir), "logs", "session_config.json")
        try:
            import json
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"session_id": session_id}, f, indent=4)
        except Exception:
            pass
            
        # Actualizar cabecera de estado persistente del chat
        self.lbl_active_session.setText(f"ACTIVO: {project_name.upper()} > {title.upper()}")
        self.lbl_active_session.setStyleSheet("""
            font-family: 'Consolas', 'Fira Code', monospace;
            font-size: 11px;
            color: #00FF66;
            background-color: rgba(0, 255, 102, 0.05);
            border: 1px solid rgba(0, 255, 102, 0.2);
            border-radius: 4px;
            padding: 6px;
            margin-bottom: 5px;
        """)
        
        # Abrir automáticamente el Pop-up flotante del navegador para mostrar las conversaciones del proyecto
        if not hasattr(self, 'projects_dialog') or not self.projects_dialog or not self.projects_dialog.isVisible():
            self.show_projects_navigator()
        else:
            self.reload_projects_list()

    def hide_diagnostics(self):
        if self.diagnostics_window:
            self.diagnostics_window.close()

    def show_diagnostics(self):
        if not self.diagnostics_window:
            self.diagnostics_window = DiagnosticsWidget(self)
        self.diagnostics_window.show()
        self.diagnostics_window.raise_()
        self.diagnostics_window.activateWindow()
        self.diagnostics_window.run_diagnostics()

    def hide_alerts(self):
        if self.alerts_window:
            self.alerts_window.close()

    def show_alerts(self):
        if not self.alerts_window:
            self.alerts_window = AlertsWidget(self)
        self.alerts_window.show()
        self.alerts_window.raise_()
        self.alerts_window.activateWindow()
        self.alerts_window.load_alerts()

    def update_vu_meter(self, level, device_name):
        self.mic_name_lbl.setText(f"MIC: {device_name.upper()}")
        self.vu_meter.setValue(level)

    def update_chat(self, sender, text):
        color = "#00E5FF" if sender == "Alfonso" else "#F59E0B"
        new_entry = f"<span style='color:{color};'><b>[{sender.upper()}]</b></span>\n\n{text}\n\n"
        self.chat_history += new_entry
        self.chat_lbl.setMarkdown(self.chat_history)
        QTimer.singleShot(50, lambda: self.chat_lbl.verticalScrollBar().setValue(self.chat_lbl.verticalScrollBar().maximum()))
        
        # Sincronizar dinámicamente con el chat del diálogo flotante de proyectos si está abierto
        if hasattr(self, 'projects_dialog') and self.projects_dialog and self.projects_dialog.isVisible():
            cur_html = self.projects_dialog.chat_display.toHtml()
            dialog_entry = f"<p><b style='color:{color};'>[{sender.upper()}]</b><br/>{text.replace('\n', '<br/>')}</p>"
            self.projects_dialog.chat_display.setHtml(cur_html + dialog_entry)
            QTimer.singleShot(50, lambda: self.projects_dialog.chat_display.verticalScrollBar().setValue(self.projects_dialog.chat_display.verticalScrollBar().maximum()))

    def reload_projects_list(self):
        """Consulta al backend la lista de conversaciones y actualiza el QListWidget en doble columna."""
        if not hasattr(self, 'thread') or not self.thread or not self.thread.api:
            return
            
        # Comprobar si el diálogo de navegación está instanciado
        if not hasattr(self, 'projects_dialog') or not self.projects_dialog:
            return
        
        try:
            res = self.thread.api.get_conversations()
            conversations = res.get("conversations", [])
            
            # Limpiar datos previos
            self.projects_dialog.proj_list.clear()
            self.projects_dialog.conv_list.clear()
            self.projects_dialog.projects_data = {}
            
            # Agrupar conversaciones por proyecto
            projects_grouped = {}
            active_project = None
            
            for c in conversations:
                proj = c.get("project_name") or "Otros / General"
                if proj not in projects_grouped:
                    projects_grouped[proj] = []
                projects_grouped[proj].append(c)
                
                # Detectar qué proyecto contiene la conversación activa actual
                if c.get("session_id") == self.thread.session_id:
                    active_project = proj
                    
            # Guardar la caché estructurada en el diálogo flotante
            self.projects_dialog.projects_data = projects_grouped
            
            # Rellenar listado de proyectos (Columna Izquierda)
            selected_item = None
            for project in sorted(projects_grouped.keys()):
                proj_item = QListWidgetItem(f"📁 {project.upper()}")
                self.projects_dialog.proj_list.addItem(proj_item)
                
                # Si es el proyecto activo actual, guardamos la referencia para seleccionarlo
                if project == active_project:
                    selected_item = proj_item
            
            # Seleccionar automáticamente el proyecto activo actual si existe
            if selected_item:
                self.projects_dialog.proj_list.setCurrentItem(selected_item)
                self.projects_dialog.select_project(selected_item)
            elif self.projects_dialog.proj_list.count() > 0:
                # Fallback: seleccionar el primero por defecto
                first_item = self.projects_dialog.proj_list.item(0)
                self.projects_dialog.proj_list.setCurrentItem(first_item)
                self.projects_dialog.select_project(first_item)
                
        except Exception as e:
            print(f"[ERROR] No se pudo refrescar navegador de proyectos: {e}")

    def load_project_session_from_ui(self, item):
        """Carga la conversación seleccionada en la UI al hacer doble clic."""
        session_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.data(Qt.ItemDataRole.UserRole + 1)
        project = item.data(Qt.ItemDataRole.UserRole + 2)
        
        if not session_id:
            return # Cabecera de carpeta de proyecto o item inválido
            
        # Cambiar el session_id del hilo activo de Alfonso
        self.thread.session_id = session_id
        
        # Guardar persistencia en session_config.json
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(os.path.dirname(gui_dir), "logs", "session_config.json")
        try:
            import json
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"session_id": session_id}, f, indent=4)
        except Exception:
            pass
            
        # Consultar historial del backend y cargar en pantalla
        try:
            res = self.thread.api.get_memory_detail(session_id)
            messages = res.get("messages", [])
            
            # Reconstruir historial formateado
            self.chat_history = ""
            for msg in messages:
                sender = "Tú" if msg.get("role") == "user" else "Alfonso"
                content = msg.get("content") or ""
                color = "#00E5FF" if sender == "Alfonso" else "#F59E0B"
                self.chat_history += f"<span style='color:{color};'><b>[{sender.upper()}]</b></span>\n\n{content}\n\n"
                
            if not self.chat_history:
                self.chat_history = f"**HISTORIAL DE CONVERSACIÓN INICIADO**\n\n*Proyecto: {project} — Título: {title}*\n\n"
                
            self.chat_lbl.setMarkdown(self.chat_history)
            
            # Actualizar cabecera de estado persistente del chat
            self.lbl_active_session.setText(f"ACTIVO: {project.upper()} > {title.upper()}")
            self.lbl_active_session.setStyleSheet("""
                font-family: 'Consolas', 'Fira Code', monospace;
                font-size: 11px;
                color: #00FF66;
                background-color: rgba(0, 255, 102, 0.05);
                border: 1px solid rgba(0, 255, 102, 0.2);
                border-radius: 4px;
                padding: 6px;
                margin-bottom: 5px;
            """)
            
            # Recargar selección de colores en el listado para reflejar la activa si el diálogo sigue abierto
            if hasattr(self, 'projects_dialog') and self.projects_dialog and self.projects_dialog.isVisible():
                for idx in range(self.projects_dialog.conv_list.count()):
                    itm = self.projects_dialog.conv_list.item(idx)
                    itm_sid = itm.data(Qt.ItemDataRole.UserRole)
                    if itm_sid:
                        if itm_sid == session_id:
                            itm.setSelected(True)
                            itm.setForeground(QColor("#00FF66"))
                        else:
                            itm.setSelected(False)
                            itm.setForeground(QColor("#CBD5E1"))
                        
        except Exception as e:
            self.update_chat("Sistema", f"Error al cargar historial: {e}")

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

    def close_gui(self):
        try:
            if hasattr(self, 'agent_process') and self.agent_process:
                self.agent_process.kill()
        except Exception:
            pass
        try:
            if hasattr(self, 'thread') and self.thread:
                self.thread.stop()
        except Exception:
            pass
        os._exit(0)

    def closeEvent(self, event):
        self.close_gui()


class CalendarWidget(QWidget):
    """Interfaz gráfica nativa para el Calendario de Alfonso (ALFONSO OS)."""
    def __init__(self, api_client):
        super().__init__()
        self.api = api_client
        self.setWindowTitle("ALFONSO CALENDAR")
        self.setMinimumSize(850, 580)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        
        self.drag_position = None

        # Estilo Glassmorphism Dark ALFONSO CALENDAR
        self.setStyleSheet("""
            QWidget {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QLabel {
                color: #E2E8F0;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton:pressed {
                background-color: #00E5FF;
                color: #0B0E14;
            }
            QScrollArea {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: rgba(20, 25, 35, 0.5);
            }
            QFrame#Separator {
                border: 1px solid rgba(255, 255, 255, 0.08);
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

        # Contenedor con borde completo ALFONSO OS
        container_frame = QFrame()
        container_frame.setObjectName("CalendarContainer")
        container_frame.setStyleSheet("""
            QFrame#CalendarContainer {
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 12px;
                background-color: rgba(20, 25, 35, 0.95);
            }
        """)
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(10)

        # ── CABECERA PERSONALIZADA (FRAMELESS HEADER) ──
        header_layout = QHBoxLayout()
        header_title = QLabel("// ALFONSO OS // CALENDAR MODULE ver 1.2.0")
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
        
        # Estilo Glassmorphism Dark EmailComposeDialog
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0E14;
                color: #CBD5E1;
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 12px;
            }
            QLabel {
                color: #F59E0B;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(15, 20, 28, 0.9);
                color: #F8FAFC;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #00E5FF;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 16px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton#SendBtn {
                background-color: rgba(0, 229, 255, 0.2);
                color: #00E5FF;
                border-color: #00E5FF;
            }
            QPushButton#SendBtn:hover {
                background-color: #00E5FF;
                color: #0B0E14;
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
        
        btn_save_draft = QPushButton("GUARDAR BORRADOR")
        btn_save_draft.clicked.connect(self.save_draft_action)
        btn_layout.addWidget(btn_save_draft)
        
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

    def save_draft_action(self):
        recipient = self.txt_recipient.text().strip()
        subject = self.txt_subject.text().strip()
        body = self.txt_body.toPlainText().strip()
        
        if not subject and not body:
            QMessageBox.warning(self, "Error", "El borrador debe tener al menos un asunto o cuerpo.")
            return
            
        res = self.api.save_draft(recipient, subject, body)
        if res.get("status") == "ok":
            QMessageBox.information(self, "Éxito", "Borrador guardado correctamente.")
            self.accept()
        else:
            QMessageBox.warning(self, "Error", f"No se pudo guardar el borrador: {res.get('message', 'Error desconocido')}")


class MailWidget(QWidget):
    """Interfaz gráfica nativa para el cliente de Correo Electrónico (ALFONSO MAIL)."""
    def __init__(self, api_client):
        super().__init__()
        self.api = api_client
        self.setWindowTitle("ALFONSO MAIL")
        self.setMinimumSize(950, 600)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        
        self.drag_position = None
        self.current_category = None  # None significa todos
        self.emails_list = []
        
        # Estilo Glassmorphism Dark ALFONSO MAIL
        self.setStyleSheet("""
            QWidget {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QLabel {
                color: #E2E8F0;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton#CategoryBtn {
                background-color: rgba(255, 255, 255, 0.03);
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 6px;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton#CategoryBtn:hover {
                background-color: rgba(0, 229, 255, 0.1);
                border-color: rgba(0, 229, 255, 0.3);
                color: #FFFFFF;
            }
            QPushButton#CategoryBtn[active="true"] {
                background-color: rgba(0, 229, 255, 0.2);
                color: #00E5FF;
                border: 1px solid #00E5FF;
                font-weight: bold;
            }
            QListWidget {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: rgba(20, 25, 35, 0.6);
                color: #F8FAFC;
            }
            QListWidget::item {
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                padding: 10px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border: 1px solid #00E5FF;
            }
            QScrollArea {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: transparent;
            }
            QFrame#Separator {
                border: 1px solid rgba(255, 255, 255, 0.08);
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

        # Contenedor con borde Glassmorphism
        container_frame = QFrame()
        container_frame.setObjectName("MailContainer")
        container_frame.setStyleSheet("""
            QFrame#MailContainer {
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 12px;
                background-color: rgba(20, 25, 35, 0.95);
            }
        """)
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(10)

        # ── CABECERA DE LA VENTANA ──
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        header_title = QLabel("// ALFONSO OS // MAIL CLIENT MODULE ver 1.0.0")
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
            ("📤 ENVIADOS", "sent"),
            ("📝 BORRADORES", "draft"),
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
            
            date_str = email.get("received_at", "")
            if date_str and len(date_str) > 16:
                date_str = date_str[:16].replace("T", " ")
            elif date_str:
                date_str = date_str[:16]
            
            # Estilo negrita si no está leído
            if date_str:
                item_text = f"{imp_badge} {sender}  ({date_str})\n      {subj}"
            else:
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



class ConfigWidget(QWidget):
    """Panel de Configuración nativo para Alfonso OS."""
    def __init__(self, parent_dashboard):
        super().__init__()
        self.dashboard = parent_dashboard
        self.setWindowTitle("ALFONSO CONFIGURATION")
        self.setMinimumSize(450, 480)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.drag_position = None

        # Estilo Glassmorphism Dark
        self.setStyleSheet("""
            QWidget {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QLabel {
                color: #94A3B8;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton#SaveBtn {
                background-color: rgba(0, 229, 255, 0.15);
                border: 1px solid #00E5FF;
                color: #00E5FF;
            }
            QPushButton#SaveBtn:hover {
                background-color: #00E5FF;
                color: #0B0E14;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: rgba(15, 20, 28, 0.9);
                color: #F8FAFC;
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #00E5FF;
            }
            QFrame#ConfigContainer {
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 12px;
                background-color: rgba(20, 25, 35, 0.95);
            }
        """)

        self.setup_ui()
        self.load_values()

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

        container_frame = QFrame()
        container_frame.setObjectName("ConfigContainer")
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(18)

        # ── CABECERA PERSONALIZADA ──
        header_layout = QHBoxLayout()
        header_title = QLabel("// ALFONSO OS // CONFIGURATION PANEL ver 1.0.0")
        header_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        
        btn_close = QPushButton("[X]")
        btn_close.setFixedWidth(40)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #FFB800;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #FF4B4B;
            }
        """)
        btn_close.clicked.connect(self.close)
        
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_close)
        container_layout.addLayout(header_layout)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid rgba(255, 255, 255, 0.08);")
        container_layout.addWidget(sep)

        # ── FORMULARIO DE CONFIGURACIÓN ──
        from PyQt6.QtWidgets import QComboBox, QSpinBox, QDoubleSpinBox
        form_layout = QFormLayout()
        form_layout.setVerticalSpacing(12)
        form_layout.setHorizontalSpacing(20)

        self.input_url = QLineEdit()
        self.input_keyword = QLineEdit()
        
        self.combo_model = QComboBox()
        self.combo_model.addItems(["tiny", "base", "small", "medium", "large"])
        
        self.spin_device = QSpinBox()
        self.spin_device.setRange(0, 32)
        
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.0, 1.0)
        self.spin_threshold.setSingleStep(0.01)
        self.spin_threshold.setValue(0.03)

        form_layout.addRow(QLabel("URL Servidor:"), self.input_url)
        form_layout.addRow(QLabel("Palabra Clave:"), self.input_keyword)
        form_layout.addRow(QLabel("Modelo de Voz:"), self.combo_model)
        form_layout.addRow(QLabel("ID Micrófono:"), self.spin_device)
        form_layout.addRow(QLabel("Umbral Ruido:"), self.spin_threshold)

        container_layout.addLayout(form_layout)

        # Separador inferior
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("border: 1px solid rgba(255, 255, 255, 0.08);")
        container_layout.addWidget(sep2)

        # Botones de Acción
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()
        
        self.btn_cancel = QPushButton("CANCELAR")
        self.btn_cancel.clicked.connect(self.close)
        
        self.btn_save = QPushButton("APLICAR CAMBIOS")
        self.btn_save.setObjectName("SaveBtn")
        self.btn_save.clicked.connect(self.save_values)
        
        actions_layout.addWidget(self.btn_cancel)
        actions_layout.addWidget(self.btn_save)
        container_layout.addLayout(actions_layout)

        window_layout.addWidget(container_frame)

    def load_values(self):
        c = self.dashboard.config
        self.input_url.setText(c.get('url', "http://localhost:8000"))
        self.input_keyword.setText(c.get('keyword', "alfonso"))
        
        model_val = c.get('model', "tiny")
        idx = self.combo_model.findText(model_val)
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
            
        self.spin_device.setValue(c.get('device', 8))
        self.spin_threshold.setValue(c.get('threshold') if c.get('threshold') is not None else 0.03)

    def save_values(self):
        c = self.dashboard.config
        c['url'] = self.input_url.text().strip()
        c['keyword'] = self.input_keyword.text().strip()
        c['model'] = self.combo_model.currentText()
        c['device'] = self.spin_device.value()
        c['threshold'] = self.spin_threshold.value()

        # Mostrar aviso de éxito
        QMessageBox.information(
            self, 
            "Configuración Guardada", 
            "Los parámetros del sistema operativo Alfonso OS han sido actualizados con éxito."
        )
        self.close()


class DiagnosticsWidget(QWidget):
    """Panel de Diagnósticos y Telemetría nativo para Alfonso OS."""
    def __init__(self, parent_dashboard):
        super().__init__()
        self.dashboard = parent_dashboard
        self.setWindowTitle("ALFONSO DIAGNOSTICS")
        self.setMinimumSize(600, 520)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.drag_position = None

        self.setStyleSheet("""
            QWidget {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QLabel {
                color: #94A3B8;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QTextBrowser {
                background-color: rgba(15, 20, 28, 0.9);
                color: #10B981;
                font-family: 'Consolas', 'Fira Code', monospace;
                font-size: 11px;
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 6px;
                padding: 10px;
            }
            QFrame#DiagContainer {
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 12px;
                background-color: rgba(20, 25, 35, 0.95);
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

        container_frame = QFrame()
        container_frame.setObjectName("DiagContainer")
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        # Cabecera
        header_layout = QHBoxLayout()
        header_title = QLabel("// ALFONSO OS // DIAGNOSTICS & TELEMETRY ver 1.0.0")
        header_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        
        btn_close = QPushButton("[X]")
        btn_close.setFixedWidth(40)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #FFB800;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #FF4B4B;
            }
        """)
        btn_close.clicked.connect(self.close)
        
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_close)
        container_layout.addLayout(header_layout)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid rgba(255, 255, 255, 0.08);")
        container_layout.addWidget(sep)

        # Estado rápido del sistema
        self.status_layout = QGridLayout()
        self.status_layout.setSpacing(10)
        
        self.lbl_net_status = QLabel("VERIFICANDO RED...")
        self.lbl_net_status.setStyleSheet("color: #FFB800; font-weight: bold;")
        self.lbl_agent_status = QLabel("VERIFICANDO AGENTE...")
        self.lbl_agent_status.setStyleSheet("color: #FFB800; font-weight: bold;")
        
        self.status_layout.addWidget(QLabel("Conexión Backend:"), 0, 0)
        self.status_layout.addWidget(self.lbl_net_status, 0, 1)
        self.status_layout.addWidget(QLabel("Proceso Agente:"), 1, 0)
        self.status_layout.addWidget(self.lbl_agent_status, 1, 1)
        
        container_layout.addLayout(self.status_layout)

        # Dispositivos de Entrada de Audio detectados
        container_layout.addWidget(QLabel("Dispositivos de Entrada de Audio Detectados (PyAudio):"))
        self.txt_audio_devices = QTextBrowser()
        container_layout.addWidget(self.txt_audio_devices)

        # Botón de Recarga / Test manual
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()
        
        self.btn_refresh = QPushButton("EJECUTAR TEST")
        self.btn_refresh.clicked.connect(self.run_diagnostics)
        
        self.btn_close_panel = QPushButton("CERRAR")
        self.btn_close_panel.clicked.connect(self.close)
        
        actions_layout.addWidget(self.btn_refresh)
        actions_layout.addWidget(self.btn_close_panel)
        container_layout.addLayout(actions_layout)

        window_layout.addWidget(container_frame)

    def run_diagnostics(self):
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("PROBANDO SISTEMAS...")
        self.lbl_net_status.setText("EJECUTANDO TEST DE RED...")
        self.lbl_net_status.setStyleSheet("color: #FFB800; font-weight: bold;")
        self.lbl_agent_status.setText("COMPROBANDO PROCESOS...")
        self.lbl_agent_status.setStyleSheet("color: #FFB800; font-weight: bold;")
        self.txt_audio_devices.setText("REALIZANDO BARRIDO DE HARDWARE...")
        
        QTimer.singleShot(700, self._execute_tests)

    def _execute_tests(self):
        # 1. Test de Red no-bloqueante
        url = self.dashboard.config.get('url', "http://localhost:8000")
        try:
            import urllib.request
            import time
            start_t = time.time()
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                elapsed = int((time.time() - start_t) * 1000)
                self.lbl_net_status.setText(f"ONLINE ({elapsed} ms) - Código: {resp.status}")
                self.lbl_net_status.setStyleSheet("color: #10B981; font-weight: bold;")
        except Exception as e:
            self.lbl_net_status.setText(f"OFFLINE - Error: Connection Failed")
            self.lbl_net_status.setStyleSheet("color: #FF4B4B; font-weight: bold;")

        # 2. Test del Agente secundario alfonso_agent
        if self.dashboard.agent_process and self.dashboard.agent_process.poll() is None:
            pid = self.dashboard.agent_process.pid
            self.lbl_agent_status.setText(f"ACTIVO (PID: {pid})")
            self.lbl_agent_status.setStyleSheet("color: #10B981; font-weight: bold;")
        else:
            self.lbl_agent_status.setText("INACTIVO / DETENIDO")
            self.lbl_agent_status.setStyleSheet("color: #FF4B4B; font-weight: bold;")

        # 3. Listar Dispositivos de Audio usando sounddevice (ya instalado en el entorno)
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            device_lines = []
            
            for i, d in enumerate(devices):
                if d.get("max_input_channels", 0) > 0:
                    device_lines.append(f"ID {i}: {d.get('name')} (Canales Max Entrada: {d.get('max_input_channels')})")
                    
            if device_lines:
                self.txt_audio_devices.setText("\n".join(device_lines))
            else:
                self.txt_audio_devices.setText("Ningún dispositivo de entrada de audio detectado por sounddevice.")
        except Exception as e:
            self.txt_audio_devices.setText(f"Error al inicializar sounddevice o escanear dispositivos:\n{str(e)}")

        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("EJECUTAR TEST")


class AlertsWidget(QWidget):
    """Centro de Alertas y Notificaciones del Sistema Alfonso OS."""
    def __init__(self, parent_dashboard):
        super().__init__()
        self.dashboard = parent_dashboard
        self.setWindowTitle("ALFONSO ALERTS")
        self.setMinimumSize(500, 400)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.drag_position = None

        self.setStyleSheet("""
            QWidget {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QLabel {
                color: #94A3B8;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.15);
                color: #FFFFFF;
                border-color: rgba(0, 229, 255, 0.4);
            }
            QPushButton#ClearBtn {
                background-color: rgba(255, 75, 75, 0.15);
                border: 1px solid #FF4B4B;
                color: #FF4B4B;
            }
            QPushButton#ClearBtn:hover {
                background-color: #FF4B4B;
                color: #0B0E14;
            }
            QListWidget {
                background-color: rgba(15, 20, 28, 0.9);
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 8px;
                padding: 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #F8FAFC;
            }
            QFrame#AlertsContainer {
                border: 1px solid rgba(255, 75, 75, 0.4);
                border-radius: 12px;
                background-color: rgba(20, 25, 35, 0.95);
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

        container_frame = QFrame()
        container_frame.setObjectName("AlertsContainer")
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        # Cabecera
        header_layout = QHBoxLayout()
        header_title = QLabel("// ALFONSO OS // ALERTS & HEALTH CENTER ver 1.0.0")
        header_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #FF4B4B; letter-spacing: 1px;")
        
        btn_close = QPushButton("[X]")
        btn_close.setFixedWidth(40)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #FF4B4B;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #FFFFFF;
            }
        """)
        btn_close.clicked.connect(self.close)
        
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_close)
        container_layout.addLayout(header_layout)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid rgba(255, 75, 75, 0.2);")
        container_layout.addWidget(sep)

        # Lista de Alertas
        self.list_widget = QListWidget()
        container_layout.addWidget(self.list_widget)

        # Botón de Despejar
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()
        
        self.btn_clear = QPushButton("DESPEJAR ALERTAS")
        self.btn_clear.setObjectName("ClearBtn")
        self.btn_clear.clicked.connect(self.clear_all)
        
        self.btn_close_panel = QPushButton("CERRAR")
        self.btn_close_panel.clicked.connect(self.close)
        
        actions_layout.addWidget(self.btn_clear)
        actions_layout.addWidget(self.btn_close_panel)
        container_layout.addLayout(actions_layout)

        window_layout.addWidget(container_frame)

    def load_alerts(self):
        self.list_widget.clear()
        
        # Generar alertas en caliente según estado real
        alerts = []
        
        # 1. Comprobar red
        url = self.dashboard.config.get('url', "http://localhost:8000")
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception:
            alerts.append("⚠️ [RED] Conexión Backend Offline - No se pudo contactar con " + url)

        # 2. Comprobar Micrófono
        dev_id = self.dashboard.config.get('device', 8)
        alerts.append(f"⚠️ [AUDIO] Entrada de audio ID [{dev_id}] en escucha activa.")
        
        # 3. Mensaje informativo de inicio
        alerts.append("ℹ️ [SISTEMA] Alfonso OS core v3.7.19 cargado en espacio de usuario.")

        for msg in alerts:
            item = QListWidgetItem(msg)
            if "⚠️" in msg:
                item.setForeground(QColor("#FFB800"))
            else:
                item.setForeground(QColor("#00E5FF"))
            self.list_widget.addItem(item)

    def clear_all(self):
        self.list_widget.clear()
        self.dashboard.alert_btn.setText(" 0 ALERTS ")
        self.dashboard.alert_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 10);
                color: #CBD5E1;
                border: 2px solid rgba(255, 255, 255, 0.2);
                font-weight: bold;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 20);
                color: #FFFFFF;
            }
        """)
        QMessageBox.information(self, "Alertas Limpias", "Todas las notificaciones de estado han sido despejadas.")
        self.close()


class ProjectNavigatorDialog(QDialog):
    """Ventana flotante Pop-up del Proyecto Activo con Chat integrado y Canales temáticos."""
    def __init__(self, parent_dashboard):
        super().__init__(parent_dashboard)
        self.dashboard = parent_dashboard
        self.setWindowTitle("WORKSPACE NAVIGATOR")
        self.setMinimumSize(960, 600)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.drag_position = None
        self.projects_data = {} # Caché estructurada
        self.active_project_name = "default"
        self.active_session_id = "default"
        
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0E14;
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QFrame#DialogContainer {
                border: 1px solid rgba(0, 240, 255, 0.35);
                border-radius: 12px;
                background-color: rgba(18, 23, 32, 0.98);
            }
            QLabel {
                color: #CBD5E1;
                font-family: 'Consolas', 'Fira Code', monospace;
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
        
        container_frame = QFrame()
        container_frame.setObjectName("DialogContainer")
        container_layout = QVBoxLayout(container_frame)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)
        
        # Cabecera
        header_layout = QHBoxLayout()
        self.header_title = QLabel("// ALFONSO OS // ACTIVE WORKSPACE")
        self.header_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #00F0FF; letter-spacing: 1.5px;")
        
        btn_close = QPushButton("[X]")
        btn_close.setFixedWidth(40)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #00F0FF;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #FFFFFF;
            }
        """)
        btn_close.clicked.connect(self.close)
        
        header_layout.addWidget(self.header_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_close)
        container_layout.addLayout(header_layout)
        
        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid rgba(0, 240, 255, 0.15);")
        container_layout.addWidget(sep)
        
        # CONTENIDO: DOBLE COLUMNA (IZQ: CANALES Y PROYECTOS, DER: CONSOLA DE CHAT)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        
        # Columna Izquierda: Listado de canales temáticos del proyecto
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        
        # Selector de Proyecto (para poder conmutar de proyecto dentro del pop-up)
        lbl_proj = QLabel("📁 ACTIVE PROJECTS")
        lbl_proj.setStyleSheet("font-size: 9px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        left_layout.addWidget(lbl_proj)
        
        self.proj_list = QListWidget()
        self.proj_list.setFixedHeight(120)
        self.proj_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(10, 15, 22, 0.8);
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 6px;
                color: #A5F3FC;
                font-family: 'Consolas', 'Fira Code', monospace;
                font-size: 10px;
            }
            QListWidget::item {
                border-bottom: 1px solid rgba(255, 255, 255, 0.02);
                padding: 6px 8px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 229, 255, 0.15);
                border-left: 2px solid #00E5FF;
                color: #00E5FF;
            }
        """)
        self.proj_list.itemClicked.connect(self.select_project)
        left_layout.addWidget(self.proj_list)
        
        lbl_conv = QLabel("💬 DISCIPLINE CHANNELS")
        lbl_conv.setStyleSheet("font-size: 9px; font-weight: bold; color: #FFB800; letter-spacing: 1px;")
        left_layout.addWidget(lbl_conv)
        
        self.conv_list = QListWidget()
        self.conv_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(10, 15, 22, 0.8);
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 6px;
                color: #CBD5E1;
                font-family: 'Consolas', 'Fira Code', monospace;
                font-size: 11px;
            }
            QListWidget::item {
                border-bottom: 1px solid rgba(255, 255, 255, 0.02);
                padding: 8px 10px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 255, 102, 0.12);
                border-left: 3px solid #00FF66;
                color: #00FF66;
            }
        """)
        self.conv_list.itemClicked.connect(self.switch_channel_from_list)
        left_layout.addWidget(self.conv_list)
        content_layout.addLayout(left_layout, 2)
        
        # Columna Derecha: Consola de chat dedicada para interactuar con Alfonso en este canal/proyecto
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)
        
        self.lbl_channel_status = QLabel("CANAL: SELECCIONA UN TEMA")
        self.lbl_channel_status.setStyleSheet("""
            font-size: 10px;
            font-weight: bold;
            color: #00FF66;
            font-family: 'Consolas', monospace;
            background-color: rgba(0, 255, 102, 0.05);
            border: 1px solid rgba(0, 255, 102, 0.15);
            border-radius: 4px;
            padding: 5px;
        """)
        right_layout.addWidget(self.lbl_channel_status)
        
        # Historial de chat dedicado en el pop-up
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setStyleSheet("""
            QTextBrowser {
                background-color: rgba(10, 15, 22, 0.9);
                border: 1px solid rgba(0, 240, 255, 0.2);
                border-radius: 6px;
                color: #CBD5E1;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                padding: 10px;
            }
        """)
        right_layout.addWidget(self.chat_display, 1)
        
        # Entrada de texto dedicada
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        
        self.txt_input = QTextEdit()
        self.txt_input.setFixedHeight(50)
        self.txt_input.setPlaceholderText("Escribe un mensaje para Alfonso en este canal...")
        self.txt_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(8, 12, 18, 0.9);
                border: 1px solid rgba(0, 240, 255, 0.3);
                border-radius: 4px;
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                padding: 5px;
            }
            QTextEdit:focus {
                border-color: #00F0FF;
            }
        """)
        self.txt_input.installEventFilter(self) # Para capturar Enter al enviar
        input_layout.addWidget(self.txt_input, 1)
        
        btn_send = QPushButton("ENVIAR")
        btn_send.setFixedSize(80, 50)
        btn_send.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 240, 255, 0.1);
                color: #00F0FF;
                border: 1px solid rgba(0, 240, 255, 0.35);
                font-weight: bold;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(0, 240, 255, 0.25);
                border-color: #00F0FF;
            }
        """)
        btn_send.clicked.connect(self.send_message_from_dialog)
        input_layout.addWidget(btn_send)
        
        right_layout.addLayout(input_layout)
        content_layout.addLayout(right_layout, 3)
        
        container_layout.addLayout(content_layout, 1)
        
        # Botones inferiores
        bottom_layout = QHBoxLayout()
        btn_refresh = QPushButton("REFRESCAR WORKSPACE")
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 240, 255, 0.03);
                color: #00F0FF;
                border: 1px solid rgba(0, 240, 255, 0.2);
                font-size: 10px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(0, 240, 255, 0.1);
            }
        """)
        btn_refresh.clicked.connect(self.dashboard.reload_projects_list)
        
        btn_close_dlg = QPushButton("MINIMIZAR")
        btn_close_dlg.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.03);
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                font-size: 10px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }
        """)
        btn_close_dlg.clicked.connect(self.close)
        
        bottom_layout.addWidget(btn_refresh)
        bottom_layout.addStretch()
        bottom_layout.addWidget(btn_close_dlg)
        container_layout.addLayout(bottom_layout)
        
        window_layout.addWidget(container_frame)

    def eventFilter(self, obj, event):
        """Captura la pulsación de la tecla enter para enviar mensajes."""
        if obj is self.txt_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.send_message_from_dialog()
                return True
        return super().eventFilter(obj, event)

    def select_project(self, item):
        """Muestra en la lista de abajo las conversaciones asociadas al proyecto seleccionado."""
        display_name = item.text().replace("📁 ", "").strip().upper()
        self.active_project_name = display_name
        self.conv_list.clear()
        
        # Buscar el proyecto de forma insensible a mayúsculas y minúsculas en la caché
        conversations = []
        for key, val in self.projects_data.items():
            if key.strip().upper() == display_name:
                conversations = val
                break
                
        selected_item = None
        for c in conversations:
            title = c.get("title") or "Sin título"
            session_id = c.get("session_id")
            discipline = c.get("discipline") or "general"
            
            display_text = f"[{discipline.upper()}] {title}"
            list_item = QListWidgetItem(display_text)
            
            list_item.setData(Qt.ItemDataRole.UserRole, session_id)
            list_item.setData(Qt.ItemDataRole.UserRole + 1, title)
            list_item.setData(Qt.ItemDataRole.UserRole + 2, key)
            
            if session_id == self.dashboard.thread.session_id:
                selected_item = list_item
                
            self.conv_list.addItem(list_item)
            
        if selected_item:
            self.conv_list.setCurrentItem(selected_item)
            self.switch_channel_from_list(selected_item)
        elif self.conv_list.count() > 0:
            first_itm = self.conv_list.item(0)
            self.conv_list.setCurrentItem(first_itm)
            self.switch_channel_from_list(first_itm)

    def switch_channel_from_list(self, item):
        """Conmuta la conversación activa en el hilo del asistente y refresca el historial del chat."""
        session_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.data(Qt.ItemDataRole.UserRole + 1)
        project = item.data(Qt.ItemDataRole.UserRole + 2)
        
        if not session_id:
            return
            
        self.active_session_id = session_id
        
        # Cambiar el session_id del hilo activo de Alfonso en background
        self.dashboard.thread.session_id = session_id
        
        # Sincronizar en sesión persistente
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(os.path.dirname(gui_dir), "logs", "session_config.json")
        try:
            import json
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"session_id": session_id}, f, indent=4)
        except Exception:
            pass
            
        # Actualizar banner de estado
        self.lbl_channel_status.setText(f"ACTIVO: {project.upper()} > {title.upper()}")
        self.header_title.setText(f"// ALFONSO OS // WORKSPACE: {project.upper()}")
        self.dashboard.lbl_active_session.setText(f"ACTIVO: {project.upper()} > {title.upper()}")
        
        # Cargar historial en el panel de chat del Pop-up
        self.load_dialog_chat_history(session_id, project, title)

    def load_dialog_chat_history(self, session_id, project, title):
        try:
            res = self.dashboard.thread.api.get_memory_detail(session_id)
            messages = res.get("messages", [])
            
            chat_html = ""
            for msg in messages:
                sender = "Tú" if msg.get("role") == "user" else "Alfonso"
                content = msg.get("content") or ""
                color = "#00E5FF" if sender == "Alfonso" else "#F59E0B"
                chat_html += f"<p><b style='color:{color};'>[{sender.upper()}]</b><br/>{content.replace('\n', '<br/>')}</p>"
                
            if not chat_html:
                chat_html = f"<p style='color:#64748B;'><i>No hay mensajes previos en este canal. Inicia el diálogo.</i></p>"
                
            self.chat_display.setHtml(chat_html)
            QTimer.singleShot(50, lambda: self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum()))
            
        except Exception as e:
            self.chat_display.setHtml(f"<p style='color:#EF4444;'>Error cargando historial: {e}</p>")

    def send_message_from_dialog(self):
        """Envía el mensaje desde el cuadro de texto del Pop-up y lo procesa."""
        text = self.txt_input.toPlainText().strip()
        if not text:
            return
            
        self.txt_input.clear()
        
        # Si el asistente está en modo de audio normal, lo forzamos a texto para procesar rápido
        if not self.dashboard.text_mode_enabled:
            self.dashboard.toggle_text_mode()
            
        # Añadimos localmente a la ventana del pop-up el mensaje de "Tú"
        cur_html = self.chat_display.toHtml()
        user_msg_html = f"<p><b style='color:#F59E0B;'>[TÚ]</b><br/>{text.replace('\n', '<br/>')}</p>"
        self.chat_display.setHtml(cur_html + user_msg_html)
        QTimer.singleShot(50, lambda: self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum()))
        
        # Lanzar el envío de mensaje a Alfonso
        self.dashboard.thread.send_text_message(text)


def launch(config):
    app = QApplication(sys.argv)
    dashboard = AlfonsoHUDDashboard(config)
    dashboard.show()
    sys.exit(app.exec())