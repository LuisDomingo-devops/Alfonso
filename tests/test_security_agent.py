import os
import shutil
import pytest
from pathlib import Path
from app.domain.agents.security.security_agent import CyberSecurityAgent

@pytest.fixture
def agent():
    # Retornar una nueva instancia aislada para pruebas
    return CyberSecurityAgent()

def test_waf_heuristics(agent):
    # Peticiones normales válidas
    assert not agent.inspect_request("127.0.0.1", "/api/chat", "POST", {}, '{"message": "hola"}')
    assert not agent.inspect_request("127.0.0.1", "/dev/run", "POST", {}, "subprocess.run('echo hello')") # /dev está exento de cmd injection básico
    assert not agent.inspect_request("127.0.0.1", "/calendar/events?start_date=2026-07-01&end_date=2026-07-31", "GET", {}, "")
    assert not agent.inspect_request("127.0.0.1", "/api/chat", "POST", {}, '{"message": "I love R&B music & programming"}')

    # Path traversal
    assert agent.inspect_request("127.0.0.1", "/api/files/../../etc/passwd", "GET", {}, "")
    assert agent.is_blocked("127.0.0.1")

    # SQL Injection
    agent2 = CyberSecurityAgent()
    assert agent2.inspect_request("127.0.0.2", "/api/users?id=1%20or%201=1", "GET", {}, "")
    assert agent2.is_blocked("127.0.0.2")

    # Command Injection fuera de /dev
    agent3 = CyberSecurityAgent()
    assert agent3.inspect_request("127.0.0.3", "/api/any", "POST", {}, "; rm -rf /")
    assert agent3.is_blocked("127.0.0.3")

def test_rate_limiting(agent):
    ip = "192.168.1.100"
    # Hacer 101 peticiones
    for i in range(101):
        blocked = agent.inspect_request(ip, "/api/chat", "POST", {}, "hello")
        if blocked:
            break
    
    assert agent.is_blocked(ip)
    assert any(a["type"] == "IP_BLOCKED" for a in agent.alerts)

@pytest.mark.asyncio
async def test_system_scan(agent, tmp_path):
    # Guardar directorios originales para restaurar
    original_sandbox = agent.sandbox_path = Path("data/dev_sandbox")
    
    # Simular sandbox de desarrollo usando tmp_path
    test_sandbox = tmp_path / "dev_sandbox"
    test_sandbox.mkdir()
    agent.sandbox_path = test_sandbox
    
    # Escribir código vulnerable
    vuln_file = test_sandbox / "vuln.py"
    vuln_file.write_text("eval(input())\nexec('print(1)')", encoding="utf-8")
    
    # Modificar ruta temporalmente del escaneo del sandbox en os.walk
    # security_agent usa directamente Path("data/dev_sandbox"), así que usaremos patching básico o crearemos el archivo en el sandbox real pero lo limpiaremos.
    # Para ser 100% seguros y no ensuciar, podemos crear el archivo en data/dev_sandbox/test_temp_security.py y luego borrarlo.
    real_sandbox = Path("data/dev_sandbox")
    real_sandbox.mkdir(parents=True, exist_ok=True)
    temp_file = real_sandbox / "test_temp_security_vuln.py"
    temp_file.write_text("eval(input())\nexec('print')", encoding="utf-8")
    
    # Crear archivo .env de prueba inseguro
    env_file = Path(".env")
    original_env_content = None
    if env_file.exists():
        original_env_content = env_file.read_text(encoding="utf-8")
    
    # Escribir env vulnerable
    env_file.write_text("ALFONSO_API_KEY=1234\nMY_SECRET=123\n", encoding="utf-8")

    try:
        await agent.scan_system()
        
        # Verificar alertas
        alert_types = [a["type"] for a in agent.alerts]
        assert "SANDBOX_VULNERABILITY" in alert_types
        assert "INSECURE_CONFIGURATION" in alert_types
        assert "WEAK_CREDENTIALS" in alert_types
    finally:
        # Limpieza
        if temp_file.exists():
            temp_file.unlink()
        if original_env_content is not None:
            env_file.write_text(original_env_content, encoding="utf-8")
        else:
            if env_file.exists():
                env_file.unlink()

def test_waf_normalization_and_bypasses(agent):
    # 1. Doble URL encoding en Path Traversal
    assert agent.inspect_request("127.0.0.4", "/api/files/%252E%252E%252F%252E%252E%252Fetc/passwd", "GET", {}, "")
    assert agent.is_blocked("127.0.0.4")

    # 2. Obfuscación con comentarios SQL
    agent5 = CyberSecurityAgent()
    assert agent5.inspect_request("127.0.0.5", "/api/data", "POST", {}, "1' UNI/**/ON SE/**/LECT null--")
    assert agent5.is_blocked("127.0.0.5")

    # 3. Unicode Homographs
    agent6 = CyberSecurityAgent()
    assert not agent6.inspect_request("127.0.0.6", "/api/chat", "POST", {}, "<ｓｃｒｉｐｔ>alert(1)</ｓｃｒｉｐｔ>")
    assert any(a["type"] == "XSS_DETECTION" for a in agent6.alerts)

    # 4. Inyección SQL ciega basada en tiempo (sleep)
    agent7 = CyberSecurityAgent()
    assert agent7.inspect_request("127.0.0.7", "/api/query", "POST", {}, "1'; sleep(5)--")
    assert agent7.is_blocked("127.0.0.7")
