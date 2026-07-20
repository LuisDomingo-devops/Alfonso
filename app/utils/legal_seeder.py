"""
LEGAL SEEDER — Inyección inicial de conocimiento legislativo.

¿QUÉ HACE?
Segmenta e inyecta la Constitución Española, Código Civil y Código Penal en la base de datos ChromaDB.

¿CUÁNDO LO HACE?
Se ejecuta de manera manual para sembrar o inicializar el conocimiento legal de MarcosAgent.

¿CÓMO LO HACE?
Procesando documentos planos txt e indexando los fragmentos en la colección legal de ChromaDB.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/adapters/memory/vector_memory.py (almacena y expone la búsqueda sobre esta colección)
"""

import sys
import os
import asyncio
import xml.etree.ElementTree as ET
import httpx
from pathlib import Path

# Añadir directorio raíz al path para poder importar módulos
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.adapters.memory import vector_memory
from app.utils.logger import app_logger

LAWS = {
    "Constitución Española": "BOE-A-1978-31229",
    "Código Civil": "BOE-A-1889-4763",
    "Código Penal": "BOE-A-1995-25444",
}

async def fetch_law_xml(boe_id: str) -> str:
    url = f"https://boe.es/datosabiertos/api/legislacion-consolidada/id/{boe_id}"
    print(f"Descargando norma {boe_id} de {url}...")
    headers = {"Accept": "application/xml"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Error descargando {boe_id}: {response.status_code} - {response.text[:200]}")
        return response.text

def parse_law_xml(xml_content: str, law_name: str) -> list[dict]:
    print(f"Procesando XML de {law_name}...")
    root = ET.fromstring(xml_content.encode("utf-8"))
    
    # Encontrar todos los bloques
    bloques = root.findall(".//bloque")
    articles = []
    
    for bloque in bloques:
        tipo = bloque.attrib.get("tipo")
        if tipo != "precepto":
            continue
        
        bloque_id = bloque.attrib.get("id", "")
        titulo = bloque.attrib.get("titulo", "")
        
        # Obtener la última versión del artículo (la consolidada actual)
        versions = bloque.findall("version")
        if not versions:
            continue
        
        last_version = versions[-1]
        
        # Unir todos los párrafos de texto
        paragraphs = []
        for child in last_version:
            if child.tag == "p" and child.text:
                paragraphs.append(child.text.strip())
        
        body_text = "\n".join(paragraphs)
        if not body_text.strip():
            continue
            
        full_text = f"[{law_name}] {titulo}\n{body_text}"
        
        articles.append({
            "id": f"{law_name.replace(' ', '_')}_{bloque_id}",
            "text": full_text,
            "metadata": {
                "law": law_name,
                "article_id": bloque_id,
                "title": titulo
            }
        })
        
    print(f"Se encontraron {len(articles)} artículos/preceptos en {law_name}.")
    return articles

async def seed_law(law_name: str, boe_id: str):
    try:
        xml_content = await fetch_law_xml(boe_id)
        articles = parse_law_xml(xml_content, law_name)
        
        if not articles:
            print(f"No se encontraron artículos para {law_name}.")
            return
            
        # Limpiar/refrescar la colección antes de meter datos
        vector_memory._refresh_collection()
        
        # Insertar en lotes (batching) para evitar sobrecargar memoria/DB
        batch_size = 100
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i+batch_size]
            ids = [a["id"] for a in batch]
            documents = [a["text"] for a in batch]
            metadatas = [a["metadata"] for a in batch]
            
            vector_memory.legal_collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            print(f"Indexados artículos {i+1} a {min(i+batch_size, len(articles))} de {law_name}...")
            
        print(f"¡Ingesta exitosa de {law_name}!")
    except Exception as e:
        print(f"Error procesando {law_name}: {e}")
        app_logger.exception("Error en legal_seeder")

async def main():
    print("Iniciando la ingesta de leyes para Marcos...")
    for law_name, boe_id in LAWS.items():
        await seed_law(law_name, boe_id)
    print("¡Ingesta completa de todas las leyes en ChromaDB!")

if __name__ == "__main__":
    asyncio.run(main())
