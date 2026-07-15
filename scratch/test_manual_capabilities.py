import urllib.request
import urllib.error
import json
import sys
import time

BASE_URL = "http://localhost:8000"

def make_request(path, method="GET", payload=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = e.reason
        return e.code, err_body
    except Exception as e:
        return 0, str(e)

def run_test_endpoint(name, path, method="GET", payload=None, expected_status=200):
    status, body = make_request(path, method, payload)
    if status == expected_status or (expected_status == 200 and status in (200, 201)):
        print(f"  [PASS] {name} ({method} {path}) -> Status {status}")
        return True, body
    else:
        print(f"  [FAIL] {name} ({method} {path}) -> Status {status} (Expected {expected_status})")
        print(f"         Detail: {body}")
        return False, body

def main():
    print("Iniciando pruebas manuales de endpoints de Alfonso...")
    
    # 1. Health
    run_test_endpoint("Health check", "/health")
    
    # 2. Tools
    run_test_endpoint("List tools", "/tools")
    
    # 3. Agents
    run_test_endpoint("List agents", "/agents")
    
    # 4. Metrics
    run_test_endpoint("Get metrics", "/metrics")
    
    # 5. Memory
    run_test_endpoint("Get memory sessions", "/memory")
    run_test_endpoint("Get memory details", "/memory/test_session")
    run_test_endpoint("Delete memory session", "/memory/test_session", method="DELETE")
    
    # 6. Calendar
    evt_payload = {
        "title": "Prueba Manual",
        "start_time": "2026-07-12T23:00:00",
        "end_time": "2026-07-12T23:30:00",
        "description": "Prueba de capacidad de calendario nativo",
        "location": "Oficina",
        "attendees": "luis@example.com"
    }
    passed, evt_body = run_test_endpoint("Create calendar event", "/calendar/events", method="POST", payload=evt_payload)
    event_id = None
    if passed and isinstance(evt_body, dict):
        event_id = evt_body.get("event", {}).get("id") or evt_body.get("id")
    
    run_test_endpoint("List calendar events", "/calendar/events")
    if event_id:
        run_test_endpoint("Delete calendar event", f"/calendar/events/{event_id}", method="DELETE")
    
    # 7. Mail
    run_test_endpoint("Seed mock emails", "/mail/emails/seed", method="POST")
    passed, emails = run_test_endpoint("List emails", "/mail/emails")
    email_id = None
    if passed and isinstance(emails, list) and len(emails) > 0:
        email_id = emails[0].get("id")
    
    if email_id:
        run_test_endpoint("Get email detail", f"/mail/emails/{email_id}")
        run_test_endpoint("Mark email as read", f"/mail/emails/{email_id}/read", method="POST")
        run_test_endpoint("Get draft for email", f"/mail/emails/{email_id}/draft")
    
    # 8. Dev Sandbox
    file_payload = {
        "filename": "manual_test_temp.txt",
        "content": "Contenido de prueba manual"
    }
    run_test_endpoint("Create file in dev sandbox", "/dev/files", method="POST", payload=file_payload)
    run_test_endpoint("List files in dev sandbox", "/dev/files")
    run_test_endpoint("Read file in dev sandbox", "/dev/files/manual_test_temp.txt")
    
    exec_payload = {
        "command": "echo 'Alfonso Dev Exec'"
    }
    run_test_endpoint("Execute command in dev sandbox", "/dev/execute", method="POST", payload=exec_payload)
    run_test_endpoint("Delete file in dev sandbox", "/dev/files/manual_test_temp.txt", method="DELETE")

    # 9. Security
    run_test_endpoint("Get security status", "/security/status")
    run_test_endpoint("Get security alerts", "/security/alerts")
    run_test_endpoint("Scan security status", "/security/scan", method="POST")
    
    print("\nPruebas manuales completadas.")

if __name__ == "__main__":
    main()
