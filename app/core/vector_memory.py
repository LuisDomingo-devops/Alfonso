import uuid
import httpx
from pathlib import Path
import chromadb
from app.config import settings
from app.utils.logger import orchestrator_logger


class OllamaEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    Embedding function que genera vectores usando la API de Ollama.
    Intenta usar el modelo de embeddings configurado y hace fallback al modelo principal de chat.
    """
    def __init__(self):
        self.model = settings.EMBEDDING_MODEL_NAME
        self.fallback_model = settings.MODEL_NAME

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        embeddings = []
        with httpx.Client(timeout=30.0) as client:
            for text in input:
                emb = self._get_embedding(client, self.model, text)
                if emb is None:
                    # Fallback al modelo de chat principal
                    emb = self._get_embedding(client, self.fallback_model, text)
                if emb is None:
                    # Fallback de seguridad: vector de ceros de dimensión 768 (nomic default)
                    emb = [0.0] * 768
                embeddings.append(emb)
        return embeddings

    def _get_embedding(self, client: httpx.Client, model: str, text: str) -> list[float] | None:
        try:
            # 1. Intentar con /api/embeddings
            r = client.post(
                f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                json={"model": model, "prompt": text}
            )
            if r.status_code == 200:
                return r.json().get("embedding")
            
            # 2. Intentar con /api/embed (formato nuevo)
            r = client.post(
                f"{settings.OLLAMA_BASE_URL}/api/embed",
                json={"model": model, "input": text}
            )
            if r.status_code == 200:
                embs = r.json().get("embeddings")
                if embs:
                    return embs[0]
        except Exception:
            pass
        return None


class VectorMemory:
    """
    Gestión de la memoria persistente semántica basada en ChromaDB.
    """
    def __init__(self):
        db_path = Path(settings.CHROMA_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=str(db_path))
        self.embedding_function = OllamaEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name="alfonso_memory",
            embedding_function=self.embedding_function
        )

    def add_fact(self, session_id: str, fact: str) -> None:
        """Inserta un hecho relevante en la base de datos vectorial."""
        if not fact or not fact.strip():
            return
        
        fact_id = str(uuid.uuid4())
        self.collection.add(
            documents=[fact.strip()],
            metadatas=[{"session_id": session_id or "global"}],
            ids=[fact_id]
        )
        orchestrator_logger.info("Recuerdo semántico guardado: %s", fact.strip())

    def query_facts(self, query: str, limit: int = 3) -> list[str]:
        """Recupera los N recuerdos más similares semánticamente a la consulta."""
        if not query or not query.strip():
            return []
        
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

    def clear(self) -> None:
        """Borra todos los registros de la colección."""
        try:
            self.client.delete_collection("alfonso_memory")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name="alfonso_memory",
            embedding_function=self.embedding_function
        )


# Instancia única global
vector_memory = VectorMemory()
