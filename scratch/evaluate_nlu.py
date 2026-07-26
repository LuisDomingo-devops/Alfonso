import asyncio
import sys
import json
from pathlib import Path

# Agregar directorio raíz al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.adapters.llm_client import OllamaClient, extract_json_robust
from app.config import settings

# Dataset de prueba NLU (Frases de usuario reales vs. Herramienta y argumentos esperados)
NLU_TEST_CASES = [
    {
        "query": "Abre la calculadora en mi ordenador por favor",
        "expected_tool": "open_application",
        "expected_args": {"command": "calculadora"}
    },
    {
        "query": "Cierra el navegador chrome",
        "expected_tool": "close_application",
        "expected_args": {"command": "chrome"}
    },
    {
        "query": "Por favor, entra a la página de google.com",
        "expected_tool": "open_url",
        "expected_args": {"url": "https://google.com"}
    },
    {
        "query": "Escribe un email para luis@example.com con asunto Reunión y dile Hola Luis",
        "expected_tool": "send_email",
        "expected_args": {"recipient": "luis@example.com", "subject": "Reunión", "body": "Hola Luis"}
    },
    {
        "query": "Búscame los correos que contengan facturas pendientes",
        "expected_tool": "read_emails",
        "expected_args": {"query": "facturas pendientes"}
    },
    {
        "query": "Agrégame un evento mañana a las 10 de la mañana que se llame Reunión de Equipo",
        "expected_tool": "create_calendar_event",
        "expected_args": {"title": "Reunión de Equipo"}
    },
    {
        "query": "Elimina la cita del calendario con ID event_123",
        "expected_tool": "delete_calendar_event",
        "expected_args": {"event_id": "event_123"}
    },
    {
        "query": "Muestra el contenido de la carpeta de descargas",
        "expected_tool": "list_directory",
        "expected_args": {"path": "downloads"}
    },
    {
        "query": "Escribe hola en mi teclado",
        "expected_tool": "keyboard_type",
        "expected_args": {"text": "hola"}
    },
    {
        "query": "Presiona la tecla enter",
        "expected_tool": "keyboard_press",
        "expected_args": {"key": "enter"}
    }
]

async def run_nlu_evaluation():
    client = OllamaClient()
    print("======================================================================")
    print("📊 INICIANDO EVALUACIÓN NLU LOCAL DE ALFONSO")
    print(f"Modelo bajo prueba: {settings.MODEL_NAME}")
    print(f"URL de Ollama: {settings.OLLAMA_BASE_URL}")
    print(f"Total casos de prueba: {len(NLU_TEST_CASES)}")
    print("======================================================================\n")

    passed_count = 0
    results = []

    for idx, case in enumerate(NLU_TEST_CASES, 1):
        query = case["query"]
        expected_tool = case["expected_tool"]
        expected_args = case["expected_args"]

        print(f"[{idx}/{len(NLU_TEST_CASES)}] Evaluando: '{query}'")
        
        try:
            # Ejecutamos la consulta en modo "tool"
            raw_response = await client.generate(query, mode="tool")
            parsed = extract_json_robust(raw_response)
            
            if not parsed:
                success = False
                error_msg = f"No se pudo extraer JSON estructurado. Respuesta cruda: '{raw_response}'"
                actual_tool, actual_args = None, None
            else:
                actual_tool = parsed.get("tool")
                actual_args = parsed.get("args", {})
                
                # Comprobación de éxito
                tool_ok = actual_tool == expected_tool
                args_ok = True
                
                # Validar que los argumentos esperados coincidan
                for key, val in expected_args.items():
                    actual_val = actual_args.get(key, "")
                    if str(val).lower() not in str(actual_val).lower():
                        args_ok = False
                        break
                
                success = tool_ok and args_ok
                error_msg = "" if success else f"Discrepancia: Esperado {expected_tool}({expected_args}), Obtenido {actual_tool}({actual_args})"

            if success:
                passed_count += 1
                print("   ✅ PASADO")
            else:
                print(f"   ❌ FALLADO: {error_msg}")

            results.append({
                "query": query,
                "success": success,
                "expected": f"{expected_tool}({expected_args})",
                "obtained": f"{actual_tool}({actual_args})" if parsed else raw_response[:100],
                "error": error_msg
            })

        except Exception as e:
            print(f"   💥 ERROR DURANTE INFERENCIA: {e}")
            results.append({
                "query": query,
                "success": False,
                "expected": f"{expected_tool}({expected_args})",
                "obtained": "ERROR",
                "error": str(e)
            })

    accuracy = (passed_count / len(NLU_TEST_CASES)) * 100
    print("\n======================================================================")
    print("📊 RESULTADOS FINALES DE LA EVALUACIÓN")
    print(f"Precisión General (NLU Accuracy): {accuracy:.2f}% ({passed_count}/{len(NLU_TEST_CASES)} correctos)")
    print("======================================================================\n")

    # Guardar reporte local en scratch/
    report_file = Path("scratch/nlu_evaluation_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "model": settings.MODEL_NAME,
            "accuracy": accuracy,
            "passed": passed_count,
            "total": len(NLU_TEST_CASES),
            "results": results
        }, f, indent=4, ensure_ascii=False)
    
    print(f"Reporte de evaluación detallado guardado en: {report_file.resolve()}")

if __name__ == "__main__":
    asyncio.run(run_nlu_evaluation())
