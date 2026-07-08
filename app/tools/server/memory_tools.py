"""
MEMORY TOOLS — Acceso a la base de hechos y memoria semántica.

¿QUÉ HACE?
Expone herramientas para buscar u registrar información factual de largo plazo en ChromaDB.

¿CUÁNDO LO HACE?
Durante la ejecución de planes de Alfonso para recordar u almacenar hechos de forma semántica.

¿CÓMO LO HACE?
Llamando a las funciones expuestas por `app/core/vector_memory.py`.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/tool_registry.py (registra estas herramientas)
- app/core/vector_memory.py (contiene el motor de búsqueda ChromaDB)
"""

from app.adapters.memory import vector_memory
from app.utils.logger import tool_logger

async def save_user_preference(fact: str, session_id: str = "global") -> dict:
    """
    Guarda de forma persistente un hecho, hábito, preferencia o aprendizaje sobre el usuario.
    """
    fact = fact.strip()
    if not fact:
        return {"status": "error", "message": "El hecho a recordar no puede estar vacío."}
    
    try:
        fact_id = vector_memory.add_fact(session_id, fact)
        return {
            "status": "ok",
            "message": f"Hecho recordado con éxito.",
            "fact_id": fact_id,
            "fact": fact
        }
    except Exception as e:
        tool_logger.exception("Error guardando preferencia en la tool de memoria: %s", e)
        return {"status": "error", "message": f"Error guardando memoria: {e}"}

async def forget_user_fact(query: str, session_id: str = "global") -> dict:
    """
    Busca en la memoria semántica recuerdos similares a la consulta y los elimina
    si la distancia semántica es baja (< 1.25) o si hay coincidencia de palabra clave.
    """
    query = query.strip()
    if not query:
        return {"status": "error", "message": "La consulta de borrado no puede estar vacía."}
    
    try:
        # Buscar coincidencias semánticas
        candidates = vector_memory.query_facts_with_ids(query, limit=5)
        # Filtrar por sesión si no es global
        if session_id and session_id != "global":
            candidates = [c for c in candidates if c["session_id"] in (session_id, "global")]
            
        # Filtrar candidatos por umbral de distancia semántica o coincidencia de palabra clave
        matched_candidates = []
        for c in candidates:
            # Distancia menor a 1.25 es un fuerte indicador de relación semántica
            # O si el término de búsqueda está explícitamente en el texto
            is_semantic_match = c.get("distance", 2.0) < 1.25
            is_substring_match = query.lower() in c["text"].lower()
            
            if is_semantic_match or is_substring_match:
                matched_candidates.append(c)

        if not matched_candidates:
            return {"status": "ok", "message": "No se encontraron recuerdos que coincidan para olvidar."}
        
        deleted_count = 0
        deleted_facts = []
        for cand in matched_candidates:
            success = vector_memory.delete_fact_by_id(cand["id"])
            if success:
                deleted_count += 1
                deleted_facts.append(cand["text"])
                
        return {
            "status": "ok",
            "message": f"Se eliminaron {deleted_count} recuerdos que coinciden.",
            "deleted_facts": deleted_facts
        }
    except Exception as e:
        tool_logger.exception("Error olvidando hecho en la tool de memoria: %s", e)
        return {"status": "error", "message": f"Error borrando memoria: {e}"}

async def get_user_profile(session_id: str = "global") -> dict:
    """
    Obtiene todos los hechos y preferencias que el asistente recuerda sobre el usuario.
    """
    try:
        all_facts = vector_memory.get_all_facts()
        # Filtrar por sesión
        if session_id and session_id != "global":
            filtered = [f for f in all_facts if f["session_id"] in (session_id, "global")]
        else:
            filtered = all_facts
            
        facts_list = [f["text"] for f in filtered]
        return {
            "status": "ok",
            "facts": facts_list,
            "count": len(facts_list)
        }
    except Exception as e:
        tool_logger.exception("Error recuperando perfil de usuario: %s", e)
        return {"status": "error", "message": f"Error cargando perfil: {e}"}

# Registro de las herramientas para auto-carga
TOOLS = {
    "save_user_preference": save_user_preference,
    "forget_user_fact": forget_user_fact,
    "get_user_profile": get_user_profile,
}
