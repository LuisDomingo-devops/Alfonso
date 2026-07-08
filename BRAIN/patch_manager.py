import json
from pathlib import Path

def save_proposal(proposal: dict) -> Path:
    """
    Guarda la propuesta de evolución en la carpeta BRAIN/reports.
    Genera un archivo Markdown (.md) para lectura humana y un archivo JSON (.json) 
    con metadatos y patch_data para automatizaciones futuras.
    """
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    proposal_id = proposal.get("id", "evolution_report")
    
    # Rutas de destino
    md_path = reports_dir / f"{proposal_id}.md"
    json_path = reports_dir / f"{proposal_id}.json"
    
    # Escribir reporte Markdown
    md_content = proposal.get("content", "# Reporte sin contenido")
    md_path.write_text(md_content, encoding="utf-8")
    
    # Escribir metadatos JSON
    json_data = {
        "id": proposal_id,
        "status": proposal.get("status", "pending"),
        "patch_data": proposal.get("patch_data", {}),
        "metadata": proposal.get("metadata", {})
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return md_path
