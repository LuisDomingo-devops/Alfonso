import uuid
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from app.config import settings
from app.utils.logger import orchestrator_logger


class VectorMemory:
    """
    Gestión de la memoria persistente semántica basada en ChromaDB.
    Utiliza el modelo de embeddings local por defecto (all-MiniLM-L6-v2 via ONNX)
    para ejecutarse 100% in-process y de forma offline.
    """
    def __init__(self):
        self.db_path = Path(settings.CHROMA_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
        self._refresh_collection()

    def _refresh_collection(self):
        """Re-obtiene o crea la colección para evitar referencias obsoletas (stale references) de otros procesos."""
        try:
            self.collection = self.client.get_or_create_collection(
                name="alfonso_memory",
                embedding_function=self.embedding_function
            )
        except Exception as e:
            orchestrator_logger.warning("No se pudo refrescar la colección de ChromaDB: %s", e)

    def add_fact(self, session_id: str, fact: str) -> str:
        """
        Inserta un hecho relevante en la base de datos vectorial.
        Devuelve el ID generado para el hecho.
        """
        if not fact or not fact.strip():
            return ""
        
        self._refresh_collection()
        fact_id = str(uuid.uuid4())
        try:
            self.collection.add(
                documents=[fact.strip()],
                metadatas=[{"session_id": session_id or "global"}],
                ids=[fact_id]
            )
            orchestrator_logger.info("Recuerdo semántico guardado: %s (ID: %s)", fact.strip(), fact_id)
            return fact_id
        except Exception as e:
            orchestrator_logger.exception("Error guardando hecho en ChromaDB: %s", e)
            return ""

    def query_facts(self, query: str, limit: int = 3) -> list[str]:
        """Recupera los N recuerdos más similares semánticamente a la consulta."""
        if not query or not query.strip():
            return []
        
        self._refresh_collection()
        try:
            results = self.collection.query(
                query_texts=[query.strip()],
                n_results=limit
            )
            documents = results.get("documents")
            if documents and len(documents) > 0:
                return documents[0]
        except Exception as e:
            orchestrator_logger.exception("Error consultando ChromaDB: %s", e)
        return []

    def query_facts_with_ids(self, query: str, limit: int = 5) -> list[dict]:
        """
        Recupera los N recuerdos más similares semánticamente,
        devolviendo una lista de diccionarios con {'id', 'text', 'session_id'}.
        """
        if not query or not query.strip():
            return []
        
        self._refresh_collection()
        try:
            results = self.collection.query(
                query_texts=[query.strip()],
                n_results=limit
            )
            documents = results.get("documents")
            ids = results.get("ids")
            metadatas = results.get("metadatas")
            
            output = []
            if documents and len(documents) > 0:
                for idx, doc in enumerate(documents[0]):
                    output.append({
                        "id": ids[0][idx] if ids else "",
                        "text": doc,
                        "distance": results.get("distances")[0][idx] if results.get("distances") else 2.0,
                        "session_id": metadatas[0][idx].get("session_id", "global") if metadatas else "global"
                    })
            return output
        except Exception as e:
            orchestrator_logger.exception("Error consultando ChromaDB con IDs: %s", e)
        return []

    def delete_fact_by_id(self, fact_id: str) -> bool:
        """Borra un hecho específico por su ID."""
        self._refresh_collection()
        try:
            self.collection.delete(ids=[fact_id])
            orchestrator_logger.info("Recuerdo semántico eliminado (ID: %s)", fact_id)
            return True
        except Exception as e:
            orchestrator_logger.exception("Error borrando de ChromaDB por ID: %s", e)
            return False

    def delete_facts_by_session(self, session_id: str) -> bool:
        """Borra todos los hechos asociados a una sesión."""
        self._refresh_collection()
        try:
            self.collection.delete(where={"session_id": session_id})
            orchestrator_logger.info("Recuerdos semánticos eliminados para la sesión: %s", session_id)
            return True
        except Exception as e:
            orchestrator_logger.exception("Error borrando de ChromaDB por sesión: %s", e)
            return False

    def get_all_facts(self) -> list[dict]:
        """Obtiene todos los hechos almacenados en la colección."""
        self._refresh_collection()
        try:
            results = self.collection.get()
            documents = results.get("documents", [])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            
            output = []
            for idx, doc in enumerate(documents):
                output.append({
                    "id": ids[idx],
                    "text": doc,
                    "session_id": metadatas[idx].get("session_id", "global") if metadatas else "global"
                })
            return output
        except Exception as e:
            orchestrator_logger.exception("Error obteniendo todos los hechos de ChromaDB: %s", e)
            return []

    def clear(self) -> None:
        """Borra todos los registros de la colección."""
        try:
            self.client.delete_collection("alfonso_memory")
        except Exception:
            pass
        self._refresh_collection()


# Instancia única global
vector_memory = VectorMemory()
