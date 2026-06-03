import asyncio
from pathlib import Path
from tqdm import tqdm
from log_reader import parse_log_file, summarize_for_llm
from log_analyzer import analyze_logs
from code_generator import generate_fix
# from patch_manager import save_proposal # Desactivado temporalmente
from app.config import settings

def save_proposal_placeholder(proposals):
    """Sustituto temporal para evitar errores de importación."""
    print("\n=== INFORME DE EVOLUCIÓN (MODO PAUSA) ===")
    for p in proposals:
        print(f"\nProblema: {p['issue']['description']}")
        print(f"Propuesta: {p['proposal']}")
    return "REPORT_PAUSED"

LOG_FILES = {
    "app": Path("logs/app.log"),
    "errors": Path("logs/errors.log"),
    "llm": Path("logs/llm.log"),
    "orchestrator": Path("logs/orchestrator.log"),
    "tools": Path("logs/tools.log"),
}

# Archivos de código que puede leer el generador
CODE_FILES = {
    "app/core/orchestrator.py": Path("app/core/orchestrator.py"),
    "app/core/llm_client.py": Path("app/core/llm_client.py"),
    "app/core/intent_router.py": Path("app/core/intent_router.py"),
    "app/tools/audio_tools.py": Path("app/tools/audio_tools.py"),
    "app/prompts/tool_system.txt": Path("app/prompts/tool_system.txt"),
    "app/prompts/chat_system.txt": Path("app/prompts/chat_system.txt"),
}

async def run_evolution_cycle(
    min_issues_to_process: int = 3,
    only_severities: list[str] = None,
):
    """
    Ciclo completo: leer logs → analizar → generar propuestas → guardar informe.
    """
    only_severities = only_severities or ["critical", "high"]
    
    print("[Brain] Iniciando ciclo de evolución...")
    
    # 1. Parsear logs
    all_events = []
    log_paths = [p for p in LOG_FILES.values() if p.exists()]
    
    with tqdm(log_paths, desc="[Brain] Leyendo logs", unit="archivo") as pbar:
        for path in pbar:
            all_events.extend(parse_log_file(path))
            pbar.set_postfix({"eventos": len(all_events)})
    
    all_events.sort(key=lambda e: e.timestamp)
    
    if not all_events:
        print("[Brain] No se encontraron eventos de log para analizar. Terminando ciclo.")
        return None

    
    # 2 & 3. Analizar logs en chunks de 10 eventos
    all_issues = []
    overall_health = "good"
    chunk_size = 10
    chunks = [all_events[i : i + chunk_size] for i in range(0, len(all_events), chunk_size)]
    
    print(f"[Brain] Iniciando análisis de {len(chunks)} fragmentos de logs...")
    
    with tqdm(chunks, desc="[Brain] Analizando chunks", unit="chunk") as pbar:
        for chunk in pbar:
            try:
                summary = summarize_for_llm(chunk)
                diagnosis = await analyze_logs(summary)
                
                chunk_issues = diagnosis.get("issues", [])
                all_issues.extend(chunk_issues)
                
                # Actualizar salud global basada en los hallazgos de los chunks
                h = diagnosis.get("overall_health", "good")
                if h == "critical":
                    overall_health = "critical"
                elif h == "degraded" and overall_health != "critical":
                    overall_health = "degraded"
                    
                pbar.set_postfix({"issues": len(all_issues), "health": overall_health})
            except Exception as e:
                pbar.write(f"[Brain] Error analizando chunk: {e}")

    # Filtrar por severidad después de recolectar todos los problemas
    issues = [
        i for i in all_issues
        if i.get("severity") in only_severities
    ]
    
    print(f"[Brain] {len(issues)} problemas de severidad {only_severities} encontrados en total")
    print(f"[Brain] Estado de salud global detectado: {overall_health}")
    
    if len(issues) < min_issues_to_process:
        print("[Brain] No hay suficientes problemas críticos para generar propuestas.")
        return None
    
    # 4. Leer código relevante
    codebase = {
        name: path.read_text(encoding="utf-8")
        for name, path in CODE_FILES.items()
        if path.exists()
    }
    
    # 5. Generar propuestas de fix
    proposals = []
    max_fixes = issues[:5]
    with tqdm(max_fixes, desc="[Brain] Generando soluciones", unit="fix") as pbar:
        for issue in pbar:
            pbar.set_postfix_str(f"Procesando: {issue['description'][:30]}...")
            try:
                proposal = await generate_fix(issue, codebase)
                proposals.append(proposal)
            except Exception as e:
                pbar.write(f"[Brain] Error generando fix: {e}")
    
    # 6. Guardar informe para revisión humana
    report_path = save_proposal_placeholder(proposals)
    print(f"[Brain] Informe guardado: {report_path}")
    print(f"[Brain] Revisa el informe y aplica manualmente los fixes que consideres correctos.")
    
    return report_path