import urllib.request
import urllib.error
import json
import sys
import time

BASE_URL = "http://localhost:8000"

def send_chat(message, session_id="human_session"):
    url = f"{BASE_URL}/chat"
    headers = {"Content-Type": "application/json"}
    payload = {
        "message": message,
        "session_id": session_id
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = e.reason
        return e.code, err_body
    except Exception as e:
        return 0, str(e)

def run_test(num, message):
    print(f"\n[TEST {num}] Humano: \"{message}\"")
    print("Enviando mensaje a Alfonso...")
    start_time = time.time()
    status, response = send_chat(message)
    duration = time.time() - start_time
    
    if status == 200:
        print(f"Alfonso respondió con éxito (tardó {duration:.2f}s):")
        result = response.get("result", {})
        res_type = result.get("type", "unknown")
        print(f"  > Tipo de respuesta: {res_type}")
        if res_type == "chat":
            print(f"  > Respuesta: {result.get('response')}")
        elif res_type == "tool":
            print(f"  > Herramienta invocada: {result.get('tool_name')}")
            print(f"  > Argumentos: {result.get('args')}")
            print(f"  > Resultado herramienta: {result.get('output')}")
            if "response" in result:
                print(f"  > Respuesta final: {result.get('response')}")
        else:
            print(f"  > Detalle: {result}")
    else:
        print(f"Error al enviar mensaje. Status: {status}")
        print(f"Detalle: {response}")

def main():
    print("======================================================================")
    print(" Iniciando Simulación de Interacciones Humanas con Alfonso")
    print("======================================================================")
    
    # Pruebas de flujo de chat
    run_test(1, "Hola Alfonso, buenos días")
    run_test(2, "¿Qué hora es Alfonso?")
    run_test(3, "Crea un archivo en el sandbox llamado chat_human_test.txt con el texto 'Simulación de Humano'")
    run_test(4, "Dame una lista de los correos que tengo")
    
    print("\n======================================================================")
    print(" Simulación completada.")
    print("======================================================================")

if __name__ == "__main__":
    main()
