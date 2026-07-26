"""
CYBERSECURITY AGENT — Agente experto en ciberseguridad.

¿QUÉ HACE?
Monitorea de forma continua en segundo plano configuraciones, logs y el sandbox de desarrollo
para detectar y mitigar riesgos en tiempo real (DDoS, inyecciones SQL/comandos, accesos indebidos).
Expone interfaces para bloqueo de IPs sospechosas y responde a consultas sobre ciberseguridad.

¿CUÁNDO LO HACE?
1. Monitoreo constante iniciado desde la fase de lifespan de la app.
2. Filtrado de tráfico en tiempo real por el middleware HTTP de FastAPI.
3. Consultas directas del usuario enrutadas por PlannerOrchestrator.
"""

import os
import re
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Set, Optional

from app.adapters.llm_client import OllamaClient
from app.utils.logger import build_logger, orchestrator_logger

# Logger exclusivo de seguridad
cyber_logger = build_logger("cybersecurity", "cybersecurity.log", log_to_console=False)

class CyberSecurityAgent:
    def __init__(self):
        self.llm = OllamaClient()
        self.prompt_path = Path("app/prompts/security_system.txt")
        self.system_prompt = ""
        self._load_prompt()

        # Alertas en memoria
        self.alerts: List[Dict] = []
        self.last_scan_time: float = 0.0

        # Lista de IPs bloqueadas (Blacklist en caliente)
        self.blocked_ips: Set[str] = set()

        # Historial de peticiones para Rate Limiting {ip: [timestamps]}
        self.request_history: Dict[str, List[float]] = {}
        self.rate_limit_threshold = 100  # Peticiones máximas por minuto
        self.rate_limit_window = 60.0    # Ventana de 60 segundos

        # Firmas WAF Robustecidas (Regex compiladas)
        self.path_traversal_re = re.compile(r"\.\.[/\\]|%2e%2e", re.IGNORECASE)
        self.sql_injection_re = re.compile(
            r"\b(union\s+all\s+select|union\s+select|select\s+.*\s+from|insert\s+into|delete\s+from|drop\s+table|or\s+\d+=\d+|['\"]or['\"]|sleep\s*\(|benchmark\s*\(|pg_sleep\s*\(|coalesce\s*\()\b",
            re.IGNORECASE
        )
        self.command_injection_re = re.compile(
            r"(&&|\|\||;|\||`|\$\()|\b(bash|sh|cmd|powershell|wget|curl|nc|netcat|ncat|eval|exec)\b",
            re.IGNORECASE
        )
        self.xss_re = re.compile(
            r"<script|javascript:|onerror\s*=|onload\s*=|onmouseover\s*=|onclick\s*=|onfocus\s*=|<iframe|<svg",
            re.IGNORECASE
        )

    def _normalize_payload(self, payload: str) -> str:
        """
        Limpia, decodifica recursivamente y normaliza un payload antes de escanearlo.
        Esto previene evasiones comunes basadas en doble encoding y obfuscación Unicode o de comentarios.
        """
        if not payload:
            return ""

        # 1. Eliminar Null Bytes que puedan truncar cadenas
        payload = payload.replace("\x00", "")

        # 2. Decodificación URL recursiva (hasta 3 iteraciones)
        import urllib.parse
        last_payload = ""
        iterations = 0
        while payload != last_payload and iterations < 3:
            last_payload = payload
            payload = urllib.parse.unquote(payload)
            iterations += 1

        # 3. Normalización Unicode (NFKD) para evitar homógrafos/suplantaciones
        import unicodedata
        payload = unicodedata.normalize("NFKD", payload)

        # 4. Eliminar comentarios SQL (-- y /* ... */) para neutralizar obfuscaciones
        payload = re.sub(r"/\*.*?\*/", "", payload, flags=re.DOTALL)
        payload = re.sub(r"--.*", "", payload)
        
        # 5. Eliminar comentarios HTML <!-- ... -->
        payload = re.sub(r"<!--.*?-->", "", payload, flags=re.DOTALL)

        return payload

    def _load_prompt(self):
        try:
            self.system_prompt = self.prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            cyber_logger.warning("Prompt de CyberAgent no encontrado, usando fallback.")
            self.system_prompt = (
                "Eres CyberAgent, el experto en ciberseguridad de Alfonso. "
                "Responde de forma técnica, rigurosa y defensiva para proteger el sistema."
            )

    def add_alert(self, level: str, alert_type: str, description: str):
        """Agrega una alerta de seguridad al historial y la escribe en el log."""
        alert = {
            "id": len(self.alerts) + 1,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,  # INFO, WARNING, HIGH
            "type": alert_type,
            "description": description
        }
        self.alerts.append(alert)
        # Limitar historial de alertas en memoria a las últimas 100
        if len(self.alerts) > 100:
            self.alerts.pop(0)

        log_msg = f"[{level}] [{alert_type}] {description}"
        if level == "HIGH":
            cyber_logger.error(log_msg)
        elif level == "WARNING":
            cyber_logger.warning(log_msg)
        else:
            cyber_logger.info(log_msg)

    def is_blocked(self, ip: str) -> bool:
        """Retorna si una IP está en la lista negra."""
        return ip in self.blocked_ips

    def block_ip(self, ip: str, reason: str):
        """Bloquea inmediatamente una IP y emite una alerta crítica."""
        if ip not in self.blocked_ips:
            self.blocked_ips.add(ip)
            self.add_alert("HIGH", "IP_BLOCKED", f"IP {ip} bloqueada permanentemente en caliente. Razón: {reason}")

    def inspect_request(self, ip: str, path: str, method: str, headers: Dict[str, str], body: str) -> bool:
        """
        Inspecciona una petición entrante en tiempo real (WAF Lite + Rate Limiter).
        Retorna True si la petición debe ser rechazada/bloqueada.
        """
        # 1. Verificar si la IP ya está bloqueada
        if ip in self.blocked_ips:
            return True

        # 2. Rate Limiting (Protección DDoS / Fuerza Bruta)
        now = time.time()
        if ip not in self.request_history:
            self.request_history[ip] = []
        
        # Filtrar peticiones fuera de la ventana
        self.request_history[ip] = [t for t in self.request_history[ip] if now - t < self.rate_limit_window]
        self.request_history[ip].append(now)

        if len(self.request_history[ip]) > self.rate_limit_threshold:
            self.block_ip(ip, f"Excedido límite de peticiones ({len(self.request_history[ip])}/{self.rate_limit_threshold} en 60s)")
            return True

        # 3. Normalizar e inspeccionar inyecciones en la URL, Path y Body
        normalized_path = self._normalize_payload(path)
        normalized_body = self._normalize_payload(body)
        payloads = [normalized_path, normalized_body]
        
        for payload in payloads:
            if not payload:
                continue
            
            # Path Traversal
            if self.path_traversal_re.search(payload):
                self.block_ip(ip, f"Intento de Path Traversal detectado en payload: {payload[:100]}")
                return True

            # SQL Injection
            if self.sql_injection_re.search(payload):
                self.block_ip(ip, f"Sospecha de SQL Injection detectada en payload: {payload[:100]}")
                return True

            # Command Injection
            # Para inyección de comandos, excluimos peticiones legítimas de desarrollo que vayan a /dev o contengan rutas de sandbox
            if "/dev" not in path and self.command_injection_re.search(payload):
                self.block_ip(ip, f"Intento de inyección de comandos detectado en payload: {payload[:100]}")
                return True

            # XSS
            if self.xss_re.search(payload):
                self.add_alert("WARNING", "XSS_DETECTION", f"Posible intento de Cross-Site Scripting (XSS) desde {ip} en payload: {payload[:100]}")
                # No bloqueamos de inmediato para XSS, pero advertimos
                
        return False

    async def scan_system(self):
        """
        Realiza un escaneo del estado general de seguridad del sistema.
        Ejecutado periódicamente o bajo demanda.
        """
        cyber_logger.info("Iniciando escaneo periódico de seguridad...")
        
        # 1. Escaneo de Sandbox de desarrollo (data/dev_sandbox)
        sandbox_path = Path("data/dev_sandbox")
        if sandbox_path.exists():
            for root, _, files in os.walk(sandbox_path):
                for file in files:
                    file_path = Path(root) / file
                    # Solo archivos de código legibles
                    if file_path.suffix in [".py", ".sh", ".js"]:
                        try:
                            content = file_path.read_text(encoding="utf-8", errors="ignore")
                            # Detectar funciones peligrosas
                            if "eval(" in content:
                                self.add_alert("WARNING", "SANDBOX_VULNERABILITY", f"Función eval() detectada en archivo sandbox: {file_path.name}")
                            if "exec(" in content:
                                self.add_alert("WARNING", "SANDBOX_VULNERABILITY", f"Función exec() detectada en archivo sandbox: {file_path.name}")
                            if "subprocess.run" in content and "shell=True" in content:
                                self.add_alert("WARNING", "SANDBOX_VULNERABILITY", f"Llamada a subprocess con shell=True en sandbox: {file_path.name}")
                        except Exception as e:
                            cyber_logger.debug(f"No se pudo analizar el archivo {file_path}: {e}")

        # 2. Escaneo de archivos de configuración (.env)
        for env_file in [".env", ".env.apps"]:
            env_path = Path(env_file)
            if env_path.exists():
                try:
                    content = env_path.read_text(encoding="utf-8", errors="ignore")
                    # Verificar si hay claves API explícitas fáciles o por defecto
                    for line in content.splitlines():
                        if "=" in line and not line.strip().startswith("#"):
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.split("#")[0].strip()
                            if key in ["ALFONSO_API_KEY", "ALFONSO_BRIDGE_TOKEN"] and val == "1234":
                                self.add_alert("HIGH", "INSECURE_CONFIGURATION", f"Clave crítica {key} configurada con valor por defecto débil ('1234') en {env_file}")
                            elif any(k in key.lower() for k in ["key", "token", "password", "secret"]):
                                if len(val) < 8 and val != "":
                                    self.add_alert("WARNING", "WEAK_CREDENTIALS", f"Variable {key} en {env_file} parece tener una contraseña o clave débil (< 8 caracteres)")
                except Exception as e:
                    cyber_logger.error(f"Error escaneando archivo {env_file}: {e}")

        # 3. Escaneo de Logs recientes para detectar errores inusuales
        log_path = Path("logs/errors.log")
        if log_path.exists():
            try:
                lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                last_lines = lines[-50:] if len(lines) > 50 else lines
                error_count = sum(1 for line in last_lines if "ERROR" in line or "Exception" in line)
                if error_count > 15:
                    self.add_alert("WARNING", "HIGH_ERROR_RATE", f"Alta tasa de errores detectada en logs recientes ({error_count} errores en últimas líneas)")
            except Exception as e:
                cyber_logger.error(f"Error analizando logs: {e}")

        self.last_scan_time = time.time()
        cyber_logger.info("Escaneo de seguridad completado.")

    async def start_background_monitoring(self, interval_seconds: int = 120):
        """Loop infinito de monitoreo en segundo plano."""
        self.add_alert("INFO", "MONITOR_STARTED", "Servicio de monitoreo en segundo plano de CyberAgent iniciado.")
        while True:
            try:
                await self.scan_system()
            except Exception as e:
                cyber_logger.exception("Error en escaneo de seguridad en segundo plano: %s", e)
            await asyncio.sleep(interval_seconds)

    async def generate_response(self, query: str) -> str:
        """Genera respuesta experta a consultas de seguridad basándose en las alertas del sistema."""
        # 1. Construir contexto de seguridad de la aplicación
        active_warnings = [a for a in self.alerts if a["level"] in ["WARNING", "HIGH"]]
        
        security_status = f"""[ESTADO DE SEGURIDAD EN TIEMPO REAL]
IPs Bloqueadas actualmente: {len(self.blocked_ips)}
Último escaneo ejecutado: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_scan_time)) if self.last_scan_time else 'Nunca'}
Total de alertas activas registradas: {len(self.alerts)}

[ALERTAS ACTIVAS DE NIVEL ALTO/ADVERTENCIA]
"""
        if active_warnings:
            for w in active_warnings[-10:]:  # Mostrar últimas 10
                security_status += f"- [{w['timestamp']}] [{w['level']}] [{w['type']}] {w['description']}\n"
        else:
            security_status += "No se registran alertas de riesgo activas en el sistema.\n"

        prompt = f"""{security_status}

[CONSULTA DE CIBERSEGURIDAD DEL USUARIO]
{query}

Por favor, como experto en ciberseguridad de Alfonso, responde a la consulta anterior. Si se relaciona con las alertas listadas arriba, indícale al usuario qué significan y los pasos recomendados para remediarlas de forma segura.
"""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt}
        ]

        try:
            return await self.llm.generate(
                prompt,
                mode="chat",
                memory=self.system_prompt,
                options={
                    "num_ctx": 4096,
                    "temperature": 0.2, # Respuestas rigurosas e informativas
                }
            )
        except Exception as e:
            cyber_logger.exception("Error en la ejecución del agente CyberAgent: %s", e)
            return "Lo siento, ocurrió un error interno al consultar con el especialista en ciberseguridad."

# Instancia única del agente
security_agent = CyberSecurityAgent()
