import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSplitter, QListWidget, QTabWidget, QPlainTextEdit, QLineEdit,
    QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

class DevEditorWidget(QWidget):
    """Interfaz de desarrollo integrada (DEV STUDIO) con estilo MUTHUR OS."""
    def __init__(self, api_client):
        super().__init__()
        self.api = api_client
        self.setWindowTitle("MUTHUR DEV STUDIO")
        self.setMinimumSize(1100, 700)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        
        self.drag_position = None
        self.open_files = {}  # {filename: text_edit_widget}
        
        # Estilo retro-hacker coherente con el resto del proyecto
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
                padding: 6px 12px;
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
            QListWidget {
                border: 1px solid rgba(0, 240, 255, 30);
                background-color: rgba(5, 7, 10, 200);
                color: #FFFFFF;
            }
            QListWidget::item {
                border-bottom: 1px solid rgba(0, 240, 255, 15);
                padding: 8px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 240, 255, 25);
                color: #FFFFFF;
                border: 1px solid #00F0FF;
            }
            QTabWidget::pane {
                border: 1px solid rgba(0, 240, 255, 30);
                background-color: #030406;
            }
            QTabBar::tab {
                background-color: rgba(5, 7, 10, 255);
                border: 1px solid rgba(0, 240, 255, 30);
                color: #00F0FF;
                padding: 6px 15px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #00F0FF;
                color: #000000;
                font-weight: bold;
            }
            QPlainTextEdit {
                background-color: #05070a;
                color: #00FF66;
                border: none;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #05070a;
                color: #00FF66;
                border: 1px solid rgba(0, 240, 255, 30);
                padding: 6px;
                font-size: 11px;
            }
            QFrame#Separator {
                border: 1px solid rgba(0, 240, 255, 30);
            }
        """)

        self.setup_ui()
        self.load_file_list()

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

        # Contenedor principal con borde retro
        container_frame = QFrame()
        container_frame.setObjectName("EditorContainer")
        container_frame.setStyleSheet("""
            QFrame#EditorContainer {
                border: 2px solid #00F0FF;
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
        
        header_title = QLabel("// MUTHUR SYSTEMS // DEVELOPMENT STUDIO MODULE v1.0.0")
        header_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #00F0FF; letter-spacing: 1px;")
        header_layout.addWidget(header_title)
        
        header_layout.addStretch()
        
        btn_min = QPushButton("MINIMIZAR")
        btn_min.clicked.connect(self.close)
        header_layout.addWidget(btn_min)
        
        container_layout.addWidget(header_widget)

        # Separador
        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        container_layout.addWidget(sep)

        # ── SPLITTER PRINCIPAL (Explorador | Editor + Terminal) ──
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: rgba(0, 240, 255, 30); }")

        # PANEL DE ARCHIVOS (Izquierda)
        self.files_panel = QWidget()
        files_layout = QVBoxLayout(self.files_panel)
        files_layout.setContentsMargins(0, 0, 5, 0)
        files_layout.setSpacing(8)

        lbl_explorer = QLabel("EXPLORADOR SANDBOX")
        lbl_explorer.setStyleSheet("font-weight: bold; font-size: 10px; color: rgba(0, 240, 255, 70);")
        files_layout.addWidget(lbl_explorer)

        self.files_list = QListWidget()
        self.files_list.itemDoubleClicked.connect(self.open_selected_file)
        files_layout.addWidget(self.files_list)

        btn_files_layout = QHBoxLayout()
        self.btn_new_file = QPushButton("NUEVO")
        self.btn_new_file.clicked.connect(self.action_new_file)
        self.btn_delete_file = QPushButton("ELIMINAR")
        self.btn_delete_file.setStyleSheet("color: #FF0055; border-color: rgba(255, 0, 85, 40);")
        self.btn_delete_file.clicked.connect(self.action_delete_file)
        btn_files_layout.addWidget(self.btn_new_file)
        btn_files_layout.addWidget(self.btn_delete_file)
        files_layout.addLayout(btn_files_layout)

        main_splitter.addWidget(self.files_panel)

        # PANEL CENTRAL: EDITOR Y TERMINAL (Derecha)
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(10)

        # Splitter vertical para Editor (Arriba) y Terminal (Abajo)
        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.setStyleSheet("QSplitter::handle { background-color: rgba(0, 240, 255, 30); }")

        # Editor Area (Tabs + Control Buttons)
        editor_container = QWidget()
        editor_vbox = QVBoxLayout(editor_container)
        editor_vbox.setContentsMargins(0, 0, 0, 0)
        editor_vbox.setSpacing(6)

        editor_controls = QHBoxLayout()
        self.btn_save_file = QPushButton("GUARDAR")
        self.btn_save_file.clicked.connect(self.action_save_active_file)
        self.btn_compile_run = QPushButton("COMPILAR Y EJECUTAR")
        self.btn_compile_run.setStyleSheet("color: #00FF66; border-color: rgba(0, 255, 102, 50);")
        self.btn_compile_run.clicked.connect(self.action_compile_and_run)
        
        editor_controls.addWidget(self.btn_save_file)
        editor_controls.addWidget(self.btn_compile_run)
        editor_controls.addStretch()
        editor_vbox.addLayout(editor_controls)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        editor_vbox.addWidget(self.tab_widget)

        vertical_splitter.addWidget(editor_container)

        # Terminal Area
        terminal_container = QWidget()
        terminal_vbox = QVBoxLayout(terminal_container)
        terminal_vbox.setContentsMargins(0, 5, 0, 0)
        terminal_vbox.setSpacing(6)

        lbl_terminal = QLabel("TERMINAL (ENTORNO DE PRUEBAS SANDBOX)")
        lbl_terminal.setStyleSheet("font-weight: bold; font-size: 10px; color: #FFB800;")
        terminal_vbox.addWidget(lbl_terminal)

        self.terminal_display = QPlainTextEdit()
        self.terminal_display.setReadOnly(True)
        self.terminal_display.setPlaceholderText("LOG DE COMPILACIÓN Y EJECUCIÓN...")
        terminal_vbox.addWidget(self.terminal_display)

        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("ESCRIBA COMANDO Y PRESIONE ENTER (ej. python3 test.py)...")
        self.terminal_input.returnPressed.connect(self.action_run_terminal_command)
        terminal_vbox.addWidget(self.terminal_input)

        vertical_splitter.addWidget(terminal_container)
        right_layout.addWidget(vertical_splitter)

        main_splitter.addWidget(self.right_panel)

        # Establecer anchos iniciales del Splitter
        main_splitter.setSizes([250, 850])
        vertical_splitter.setSizes([450, 200])

        container_layout.addWidget(main_splitter)
        window_layout.addWidget(container_frame)

    def load_file_list(self):
        """Carga la lista de archivos desde el backend."""
        self.files_list.clear()
        files = self.api.get_dev_files()
        for f in files:
            self.files_list.addItem(f["name"])

    def open_selected_file(self, item):
        """Abre un archivo en una nueva pestaña del editor."""
        filename = item.text()
        if filename in self.open_files:
            self.tab_widget.setCurrentWidget(self.open_files[filename])
            return

        res = self.api.get_dev_file(filename)
        if "content" in res:
            editor = QPlainTextEdit()
            editor.setPlainText(res["content"])
            
            # Autoguardado visual / scroll
            self.open_files[filename] = editor
            index = self.tab_widget.addTab(editor, filename)
            self.tab_widget.setCurrentIndex(index)

    def action_new_file(self):
        """Solicita nombre y crea un archivo vacío en el sandbox."""
        name, ok = QInputDialog.getText(self, "Nuevo Archivo", "Nombre del archivo (ej. app.py, main.cpp, script.cs):")
        if ok and name.strip():
            filename = name.strip()
            res = self.api.save_dev_file(filename, "")
            if res.get("status") == "ok":
                self.load_file_list()
                # Abrirlo en el editor
                editor = QPlainTextEdit()
                self.open_files[filename] = editor
                index = self.tab_widget.addTab(editor, filename)
                self.tab_widget.setCurrentIndex(index)

    def action_save_active_file(self):
        """Guarda el archivo de la pestaña activa."""
        index = self.tab_widget.currentIndex()
        if index < 0:
            return
        
        filename = self.tab_widget.tabText(index)
        editor = self.tab_widget.widget(index)
        content = editor.toPlainText()
        
        res = self.api.save_dev_file(filename, content)
        if res.get("status") == "ok":
            self.terminal_display.appendPlainText(f"[SISTEMA] Archivo '{filename}' guardado correctamente.")
        else:
            self.terminal_display.appendPlainText(f"[ERROR] Error al guardar '{filename}': {res.get('message')}")

    def action_delete_file(self):
        """Elimina el archivo seleccionado del sandbox."""
        item = self.files_list.currentItem()
        if not item:
            return
        
        filename = item.text()
        reply = QMessageBox.question(
            self, "Confirmar eliminación",
            f"¿Seguro que deseas eliminar '{filename}' del sandbox?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            res = self.api.delete_dev_file(filename)
            if res.get("status") == "ok":
                self.load_file_list()
                # Si está abierto en tabs, cerrarlo
                if filename in self.open_files:
                    editor = self.open_files[filename]
                    idx = self.tab_widget.indexOf(editor)
                    if idx >= 0:
                        self.tab_widget.removeTab(idx)
                    del self.open_files[filename]
                self.terminal_display.appendPlainText(f"[SISTEMA] Archivo '{filename}' eliminado.")

    def close_tab(self, index):
        """Cierra una pestaña del editor."""
        filename = self.tab_widget.tabText(index)
        if filename in self.open_files:
            del self.open_files[filename]
        self.tab_widget.removeTab(index)

    def action_compile_and_run(self):
        """Deduce cómo compilar/ejecutar el archivo activo y ejecuta la acción."""
        index = self.tab_widget.currentIndex()
        if index < 0:
            self.terminal_display.appendPlainText("[SISTEMA] No hay ningún archivo abierto para ejecutar.")
            return
        
        # Primero guardamos el archivo
        self.action_save_active_file()
        
        filename = self.tab_widget.tabText(index)
        ext = filename.split(".")[-1].lower()
        
        cmd = ""
        if ext == "py":
            cmd = f"python3 {filename}"
        elif ext in ["c", "cpp"]:
            binary = filename.split(".")[0]
            compiler = "g++" if ext == "cpp" else "gcc"
            cmd = f"{compiler} {filename} -o {binary} && ./{binary}"
        elif ext == "cs":
            # C# compilación con mono o dotnet si estuvieran, usaremos mcs/mono o dotnet
            # Usamos mcs si existiera o dotnet run
            cmd = f"mcs {filename} && mono {filename.replace('.cs', '.exe')}"
            self.terminal_display.appendPlainText(f"[SISTEMA] Intentando compilar C# con mono/mcs...")
        else:
            self.terminal_display.appendPlainText(f"[SISTEMA] No hay regla de ejecución predefinida para extensiones '.{ext}'.")
            return
        
        self.terminal_display.appendPlainText(f"\n$ {cmd}")
        res = self.api.execute_dev_command(cmd)
        
        if res.get("stdout"):
            self.terminal_display.appendPlainText(res["stdout"])
        if res.get("stderr"):
            self.terminal_display.appendPlainText(f"Error:\n{res['stderr']}")
        self.terminal_display.appendPlainText(f"Process finished with exit code {res.get('exit_code', 0)}")

    def action_run_terminal_command(self):
        """Ejecuta un comando libre de terminal en el sandbox."""
        cmd = self.terminal_input.text().strip()
        if not cmd:
            return
        
        self.terminal_input.clear()
        self.terminal_display.appendPlainText(f"\n$ {cmd}")
        
        res = self.api.execute_dev_command(cmd)
        
        if res.get("stdout"):
            self.terminal_display.appendPlainText(res["stdout"])
        if res.get("stderr"):
            self.terminal_display.appendPlainText(f"Error:\n{res['stderr']}")
        self.terminal_display.appendPlainText(f"Process finished with exit code {res.get('exit_code', 0)}")
