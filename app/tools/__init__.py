"""
TOOLS INIT — Registro global de herramientas de Alfonso.

¿QUÉ HACE?
Importa de forma automática todos los módulos del paquete de herramientas para disparar el decorador `@tool` y registrarlos.

¿CUÁNDO LO HACE?
Al arrancar el servidor web para registrar todas las funciones ejecutables.

¿CÓMO LO HACE?
Realizando importaciones absolutas de todos los módulos de herramientas en el paquete.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/tool_registry.py (almacena el registro global de estas herramientas)
"""
