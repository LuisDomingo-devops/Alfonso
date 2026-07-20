"""
DEV SEEDER — Inyección inicial de conocimiento técnico.

¿QUÉ HACE?
Lee archivos locales con plantillas y pautas de diseño de software y los indexa en ChromaDB.

¿CUÁNDO LO HACE?
Se ejecuta de manera manual para sembrar o inicializar el conocimiento disponible para DevAgent.

¿CÓMO LO HACE?
Analizando archivos y subiéndolos mediante el cliente persistente de ChromaDB.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/adapters/memory/vector_memory.py (define el cliente y las colecciones donde se guardan los datos)
"""

from app.adapters.memory import vector_memory
from app.utils.logger import app_logger

DEV_GUIDELINES = [
    # Python
    {
        "id": "py_best_practices",
        "text": "Estándar de Python: Seguir PEP 8. Usar type hints siempre en funciones. Manejar excepciones con bloques try/except específicos. Usar docstrings en formato Google. Estructura estándar:\nif __name__ == '__main__':\n    main()"
    },
    {
        "id": "py_file_template",
        "text": "Plantilla de Python para utilidades/scripts:\nimport os\nimport sys\nfrom typing import List\n\ndef run_task(args: List[str]) -> None:\n    \"\"\"Ejecuta la tarea principal.\"\"\"\n    print(f'Procesando con args: {args}')\n\nif __name__ == '__main__':\n    run_task(sys.argv[1:])"
    },
    # C
    {
        "id": "c_best_practices",
        "text": "Estándar de C: Usar C11 o superior. Liberar siempre la memoria reservada con malloc/calloc usando free(). Comprobar punteros NULL. Usar cabeceras estándar <stdio.h>, <stdlib.h>, <string.h>. Evitar desbordamiento de búfer usando funciones seguras (snprintf en vez de sprintf)."
    },
    {
        "id": "c_file_template",
        "text": "Plantilla básica de C:\n#include <stdio.h>\n#include <stdlib.h>\n\nint main(int argc, char *argv[]) {\n    printf(\"Hello, World from C!\\n\");\n    return EXIT_SUCCESS;\n}"
    },
    # C++
    {
        "id": "cpp_best_practices",
        "text": "Estándar de C++: Usar C++17 o superior. Preferir smart pointers (std::unique_ptr, std::shared_ptr) sobre punteros crudos y delete. Usar std::string y std::vector en vez de arrays y strings de estilo C. Usar namespaces correctamente. Utilizar std::cout/std::cerr."
    },
    {
        "id": "cpp_file_template",
        "text": "Plantilla básica de C++:\n#include <iostream>\n#include <vector>\n#include <string>\n\nint main() {\n    std::vector<std::string> msgs = {\"Hello\", \"C++\", \"World\"};\n    for (const auto& msg : msgs) {\n        std::cout << msg << \" \";\n    }\n    std::cout << std::endl;\n    return 0;\n}"
    },
    # C#
    {
        "id": "cs_best_practices",
        "text": "Estándar de C#: Seguir convenciones de C#/.NET. Clases e interfaces bien estructuradas en namespaces. Utilizar properties en vez de fields públicos. Usar LINQ de forma eficiente. Liberar recursos con la declaración 'using'."
    },
    {
        "id": "cs_file_template",
        "text": "Plantilla básica de C#:\nusing System;\n\nnamespace DevSandbox {\n    class Program {\n        static void Main(string[] args) {\n            Console.WriteLine(\"Hello, World from C#!\");\n        }\n    }\n}"
    }
]

def seed_dev_knowledge():
    print("Iniciando la ingesta de conocimiento técnico para el Agente Dev...")
    try:
        vector_memory._refresh_collection()
        # Verificar si ya tiene datos
        existing = vector_memory.dev_collection.get()
        if existing and existing.get("documents") and len(existing["documents"]) > 0:
            print("La colección dev_knowledge ya contiene datos. Omitiendo semilla.")
            return
        
        documents = [item["text"] for item in DEV_GUIDELINES]
        ids = [item["id"] for item in DEV_GUIDELINES]
        
        vector_memory.dev_collection.add(
            documents=documents,
            ids=ids
        )
        print(f"Ingesta completada: {len(documents)} pautas ingresadas en dev_knowledge.")
    except Exception as e:
        print(f"Error seeding dev_knowledge: {e}")

if __name__ == '__main__':
    seed_dev_knowledge()
