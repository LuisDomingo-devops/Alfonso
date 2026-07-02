import requests
import json
import time

URL = "http://localhost:8000/chat"
headers = {"Content-Type": "application/json"}
session_id = "test_manual_session_123"

def send_message(msg):
    print(f"\n--- Enviando: '{msg}' ---")
    data = {
        "message": msg,
        "session_id": session_id
    }
    try:
        start_time = time.time()
        response = requests.post(URL, headers=headers, json=data, timeout=120)
        elapsed = time.time() - start_time
        print(f"Status Code: {response.status_code} (Tiempo: {elapsed:.2f}s)")
        if response.status_code == 200:
            res_json = response.json()
            print("Respuesta de Alfonso (JSON Completo):")
            print(json.dumps(res_json, indent=2))
        else:
            print("Error en la respuesta:")
            print(response.text)
    except Exception as e:
        print(f"Excepción al conectar con el servidor: {e}")

# Ejecutar una serie de pruebas para validar las tools en el escritorio de Windows
send_message("crea una carpeta en la ruta C:/Users/luisd/Desktop/PruebaManual")
time.sleep(2)
send_message("crea un archivo en la ruta C:/Users/luisd/Desktop/PruebaManual/prueba.txt que diga Hola Mundo")
time.sleep(2)
send_message("escribe en el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt que funciona de maravilla")
time.sleep(2)
send_message("lee el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt")
time.sleep(2)
send_message("renombra el archivo C:/Users/luisd/Desktop/PruebaManual/prueba.txt a C:/Users/luisd/Desktop/PruebaManual/prueba_ok.txt")
time.sleep(2)
send_message("dime qué hay en la carpeta C:/Users/luisd/Desktop/PruebaManual")
time.sleep(2)
send_message("elimina el archivo C:/Users/luisd/Desktop/PruebaManual/prueba_ok.txt")
time.sleep(2)
send_message("elimina la carpeta C:/Users/luisd/Desktop/PruebaManual")
