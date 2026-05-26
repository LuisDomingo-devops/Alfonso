import sys
import os
import uuid
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QWidget, QLabel, QFrame, QMessageBox, QPushButton)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QScreen

from core.api import AlfonsoAPI
from core.processor import ResponseProcessor
from services.audio import AudioService

class AssistantThread(QThread):
    """Hilo secundario para el loop de escucha de voz."""
    new_message = pyqtSignal(str, str) # sender, message
    state_changed = pyqtSignal(str)    # idle, listening, thinking, speaking

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.api = AlfonsoAPI(config['url']) if 'url' in config else AlfonsoAPI("http://localhost:8000")
        self.audio = AudioService()
        self.processor = ResponseProcessor()
        self.running = True
        self.session_id = str(uuid.uuid4())

    def run(self):
        self.state_changed.emit("connecting")
        print(f"[INFO] Intentando conectar al servidor: {self.api.base_url}")
        
        try:
            if not self.api.ping():
                print(f"[ERROR] No se pudo conectar a {self.api.base_url}. Revisa si el servidor está activo.")
                self.state_changed.emit("error")
                return
            print("[OK] Conexión con el servidor establecida.")
        except Exception as e:
            print(f"[CRITICAL] Error durante la conexión: {e}")
            self.state_changed.emit("error")
            return

        self.state_changed.emit("idle")
        keyword = self.config.get('keyword', 'alfonso')
        threshold = self.config.get('threshold', 500)
        device = self.config.get('device', None)
        model = self.config.get('model', 'tiny')
        voice = self.config.get('voice', None)

        print(f"[INFO] Micrófono: {device if device is not None else 'Predeterminado'}")
        print(f"[INFO] Umbral de voz: {threshold}")

        while self.running:
            try:
                # Fase 1: Esperar Wake Word
                wav = self.audio.record_chunk(3, device=device)
                
                if not self.audio.has_voice(wav, threshold):
                    continue

                print("[DEBUG] Voz detectada, verificando wake word...")
                res = self.api.detect_wake_word(wav, keyword, model=model)
                
                if res.get("result", {}).get("wake_word_detected"):
                    print(f"[OK] Wake word '{keyword}' detectada.")
                    self.state_changed.emit("listening")
                    self.new_message.emit("Alfonso", "Dime, te escucho...")

                    # Fase 2: Escuchar Orden
                    wav_order = self.audio.record_chunk(5, device=device)
                    self.state_changed.emit("thinking")
                    
                    stt_res = self.api.transcribe_audio(wav_order, model="small")
                    user_text = stt_res.get("result", {}).get("text", "").strip()
                    
                    if user_text:
                        self.new_message.emit("Tú", user_text)
                        chat_res = self.api.send_chat(user_text, self.session_id)
                        response_data = chat_res.get("result", {})
                        response_text = self.processor.format_response(response_data)
                        
                        self.new_message.emit("Alfonso", response_text)
                        self.state_changed.emit("speaking")
                        
                        audio_path = self.api.get_tts(response_text, voice)
                        if audio_path:
                            self.audio.play_audio_file(audio_path)
                    
                    self.state_changed.emit("idle")

            except Exception as e:
                print(f"[ERROR] Error en el loop de audio: {e}")
                self.state_changed.emit("error")
                break

class AlfonsoGUI(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        
        # Configuración de ventana tipo "Siri"
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(350, 150)
        self.move_to_bottom_center()

        # Widget principal redondeado
        self.container = QFrame()
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet("""
            #MainContainer {
                background-color: rgba(30, 30, 30, 220);
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
            QLabel {
                color: white;
                font-family: 'Segoe UI', sans-serif;
            }
        """)

        layout = QVBoxLayout()
        self.state_lbl = QLabel("Esperando...")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet("font-size: 10px; color: #888; text-transform: uppercase;")

        self.chat_lbl = QLabel("Di 'Alfonso' para empezar")
        self.chat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chat_lbl.setWordWrap(True)
        self.chat_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")

        # Indicador visual (Orb)
        self.orb = QFrame()
        self.orb.setFixedSize(10, 10)
        self.orb.setStyleSheet("background-color: #555; border-radius: 5px;")

        # Botón de cierre provisional
        self.close_button = QPushButton("Cerrar")
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #ff4b4b;
                color: white;
                border-radius: 8px;
                padding: 5px 10px;
            }
        """)
        self.close_button.clicked.connect(self.close_gui)
        
        layout.addWidget(self.state_lbl)
        layout.addWidget(self.chat_lbl)
        layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.container.setLayout(layout)
        self.setCentralWidget(self.container)

        self.start_assistant()

    def move_to_bottom_center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - 20
        self.move(x, y)

    def start_assistant(self):
        self.thread = AssistantThread(self.config)
        self.thread.new_message.connect(self.update_chat)
        self.thread.state_changed.connect(self.update_visual_state)
        self.thread.start()

    def close_gui(self):
        """Cierre forzoso del proceso para evitar bloqueos del hilo de audio."""
        if self.thread:
            self.thread.running = False
        os._exit(0)

    def update_chat(self, sender, text):
        self.chat_lbl.setText(text)

    def closeEvent(self, event):
        """Maneja el evento de cierre de la ventana."""
        if self.thread and self.thread.isRunning():
            reply = QMessageBox.question(self, 'Cerrar Alfonso',
                                         "¿Estás seguro de que quieres cerrar Alfonso?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.thread.running = False
                self.thread.wait()  # Espera a que el hilo termine
                event.accept()
            else:
                event.ignore()

    def update_visual_state(self, state):
        colors = {
            "connecting": ("#f1c40f", "Conectando..."),
            "idle": ("#555", "En espera"),
            "listening": ("#00d1ff", "Escuchando..."),
            "thinking": ("#bd00ff", "Pensando..."),
            "speaking": ("#00ff85", "Alfonso habla"),
            "error": ("#ff4b4b", "Error de conexión")
        }
        color, label = colors.get(state, ("#555", ""))
        self.state_lbl.setText(label)
        self.container.setStyleSheet(f"""
            #MainContainer {{
                background-color: rgba(30, 30, 30, 220);
                border-radius: 20px;
                border: 2px solid {color};
            }}
            QLabel {{ color: white; font-family: 'Segoe UI'; }}
        """)

def launch(config):
    app = QApplication(sys.argv)
    gui = AlfonsoGUI(config)
    gui.show()
    sys.exit(app.exec())