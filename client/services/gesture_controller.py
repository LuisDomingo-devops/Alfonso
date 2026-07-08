import cv2
import mediapipe as mp
import pyautogui
import ctypes
import threading
import time
import math
import logging

logger = logging.getLogger("gesture_controller")
logger.setLevel(logging.INFO)

# Win32 Monitor structs and functions for dual screens
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)]

def get_monitors():
    """Queries Windows OS for all active monitors, sorted left-to-right."""
    monitors = []
    
    def monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
        rect = lprcMonitor.contents
        monitors.append({
            "left": rect.left,
            "top": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top
        })
        return True

    # Check if Windows is OS
    try:
        MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_double)
        ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(monitor_enum_proc), 0)
    except Exception as e:
        logger.warning(f"Error querying monitors via ctypes: {e}. Defaulting to PyAutoGUI screen size.")
    
    if not monitors:
        w, h = pyautogui.size()
        monitors = [{"left": 0, "top": 0, "width": w, "height": h}]
    
    # Sort left-to-right
    monitors.sort(key=lambda m: m["left"])
    return monitors


class GestureController:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self._running = False
        self._thread = None
        
        # Screen configuration
        self.monitors = get_monitors()
        self.active_monitor_index = 0
        logger.info(f"Detección de pantallas completada. Monitores detectados: {self.monitors}")
        
        # MediaPipe initialization
        self.mp_hands = mp.solutions.hands
        self.mp_face_mesh = mp.solutions.face_mesh
        
        # Hand & Face mesh models
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        
        # Filtering & smoothing params
        self.alpha = 0.25  # Exponential moving average factor (lower = smoother but slightly more lag, 0.2-0.3 is optimal)
        self.prev_x, self.prev_y = pyautogui.position()
        
        # Gestures state tracking
        self.is_left_clicked = False
        self.is_right_clicked = False
        
        # Calibration / Thresholds
        # Nose horizontal ratio relative to outer corners of the eyes:
        # Looking straight should be around 0.5.
        # Threshold for looking left/right:
        self.look_left_threshold = -0.12
        self.look_right_threshold = 0.12
        
        # Cooldown timer to prevent rapid screen toggling
        self.last_screen_switch_time = 0.0
        self.screen_switch_cooldown = 1.5  # seconds
        
    def start(self):
        """Starts gesture tracking in a background thread."""
        if self._running:
            logger.warning("Gesture Controller ya se está ejecutando.")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Gesture Controller iniciado en segundo plano.")
        
    def stop(self):
        """Stops gesture tracking."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Gesture Controller detenido.")
        
    def _run_loop(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            logger.error("No se pudo acceder a la cámara web.")
            self._running = False
            return
        
        # Configure OpenCV camera resolution for fast execution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        pyautogui.FAILSAFE = False
        
        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            
            # Flip horizontally for mirrored view
            frame = cv2.flip(frame, 1)
            h, w, c = frame.shape
            
            # Convert color space for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 1. Process Face Mesh for Head Pose / Screen Selection
            face_results = self.face_mesh.process(rgb_frame)
            if face_results.multi_face_landmarks and len(self.monitors) > 1:
                landmarks = face_results.multi_face_landmarks[0].landmark
                
                # Outer corners of eyes:
                # Left eye outer corner (Landmark 33)
                # Right eye outer corner (Landmark 263)
                # Nose tip (Landmark 4)
                eye_left = landmarks[33]
                eye_right = landmarks[263]
                nose = landmarks[4]
                
                # Compute mid point between outer corners of eyes
                mid_eyes_x = (eye_left.x + eye_right.x) / 2.0
                eye_span = eye_right.x - eye_left.x
                
                if eye_span > 0:
                    # Calculate ratio of nose displacement relative to eye span
                    # Negative means nose is shifted left (looking right in mirrored view or vice-versa)
                    # Let's calibrate:
                    # Looking left: nose shifts to left relative to eyes in mirrored video feed (x decreases)
                    # Looking right: nose shifts to right relative to eyes (x increases)
                    offset = (nose.x - mid_eyes_x) / eye_span
                    
                    current_time = time.time()
                    if current_time - self.last_screen_switch_time > self.screen_switch_cooldown:
                        if offset < self.look_left_threshold and self.active_monitor_index > 0:
                            self.active_monitor_index -= 1
                            self.last_screen_switch_time = current_time
                            logger.info(f"Pantalla cambiada a la Izquierda (Index: {self.active_monitor_index}). Offset: {offset:.3f}")
                        elif offset > self.look_right_threshold and self.active_monitor_index < len(self.monitors) - 1:
                            self.active_monitor_index += 1
                            self.last_screen_switch_time = current_time
                            logger.info(f"Pantalla cambiada a la Derecha (Index: {self.active_monitor_index}). Offset: {offset:.3f}")
            
            # 2. Process Hand Landmarks for Mouse Movement and Clicks
            hand_results = self.hands.process(rgb_frame)
            if hand_results.multi_hand_landmarks:
                hand_landmarks = hand_results.multi_hand_landmarks[0].landmark
                
                # Index finger tip (Landmark 8) and PIP joint (Landmark 6)
                index_tip = hand_landmarks[8]
                wrist = hand_landmarks[0]
                middle_mcp = hand_landmarks[9]  # base of middle finger
                
                # Reference scale (palm length)
                palm_scale = math.hypot(wrist.x - middle_mcp.x, wrist.y - middle_mcp.y)
                
                # Define active sub-rectangle area of tracking in the frame to make it comfortable to reach boundaries
                tracking_margin = 0.25
                x_rel = (index_tip.x - tracking_margin) / (1.0 - 2 * tracking_margin)
                y_rel = (index_tip.y - tracking_margin) / (1.0 - 2 * tracking_margin)
                
                # Clamp coordinates to [0, 1] range
                x_rel = max(0.0, min(1.0, x_rel))
                y_rel = max(0.0, min(1.0, y_rel))
                
                # Map to current active screen bounds
                monitor = self.monitors[self.active_monitor_index]
                target_x = monitor["left"] + x_rel * monitor["width"]
                target_y = monitor["top"] + y_rel * monitor["height"]
                
                # Apply smoothing
                smooth_x = self.alpha * target_x + (1 - self.alpha) * self.prev_x
                smooth_y = self.alpha * target_y + (1 - self.alpha) * self.prev_y
                
                pyautogui.moveTo(int(smooth_x), int(smooth_y))
                self.prev_x, self.prev_y = smooth_x, smooth_y
                
                # Gesture detection for clicks
                # 1. Left Click Pinch (Index tip 8 + Thumb tip 4)
                thumb_tip = hand_landmarks[4]
                dist_left = math.hypot(index_tip.x - thumb_tip.x, index_tip.y - thumb_tip.y) / palm_scale
                
                if dist_left < 0.22:
                    if not self.is_left_clicked:
                        pyautogui.mouseDown(button='left')
                        self.is_left_clicked = True
                        logger.info("Click Izquierdo presionado (Pinch)")
                else:
                    if self.is_left_clicked:
                        pyautogui.mouseUp(button='left')
                        self.is_left_clicked = False
                        logger.info("Click Izquierdo soltado")
                
                # 2. Right Click Pinch (Middle tip 12 + Thumb tip 4)
                middle_tip = hand_landmarks[12]
                dist_right = math.hypot(middle_tip.x - thumb_tip.x, middle_tip.y - thumb_tip.y) / palm_scale
                
                if dist_right < 0.22:
                    if not self.is_right_clicked:
                        pyautogui.mouseDown(button='right')
                        self.is_right_clicked = True
                        logger.info("Click Derecho presionado (Pinch)")
                else:
                    if self.is_right_clicked:
                        pyautogui.mouseUp(button='right')
                        self.is_right_clicked = False
                        logger.info("Click Derecho soltado")
                        
            # Sleep slightly to avoid hogging CPU
            time.sleep(0.01)
            
        cap.release()


# Standalone runner for testing/verifying
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    controller = GestureController()
    print("Iniciando pruebas de GestureController...")
    print("Mueve tu mano abierta para mover el ratón.")
    print("Pellizca el índice y el pulgar para CLICK IZQUIERDO.")
    print("Pellizca el dedo corazón y el pulgar para CLICK DERECHO.")
    print("Gira la cabeza a la izquierda o derecha para cambiar de pantalla.")
    print("Presiona Ctrl+C en esta consola para salir.")
    
    try:
        controller.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        controller.stop()
        print("Detenido.")
