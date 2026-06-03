# brain/launch.py
import asyncio
import argparse
import sys
from pathlib import Path

# Asegurar que el directorio raíz 'Alfonso' esté en el path para encontrar el módulo 'app'
sys.path.append(str(Path(__file__).resolve().parent.parent))

from scheduler import run_evolution_cycle

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--severity", nargs="+", default=["critical", "high"])
    parser.add_argument("--min-issues", type=int, default=2)
    args = parser.parse_args()
    
    asyncio.run(run_evolution_cycle(
        min_issues_to_process=args.min_issues,
        only_severities=args.severity
    ))