import re
from pathlib import Path
from datetime import datetime

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LIMIT_DATE = datetime(2026, 7, 21)

# Expresión para detectar el inicio de línea con timestamp YYYY-MM-DD
TIMESTAMP_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})")

def clean_log_file(file_path: Path):
    if not file_path.is_file():
        return
        
    print(f"Procesando: {file_path.name}")
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"Error leyendo {file_path.name}: {e}")
        return
        
    lines = content.splitlines()
    new_lines = []
    
    keep_current = False
    
    for line in lines:
        match = TIMESTAMP_PATTERN.match(line)
        if match:
            date_str = match.group(1)
            try:
                line_date = datetime.strptime(date_str, "%Y-%m-%d")
                if line_date >= LIMIT_DATE:
                    keep_current = True
                else:
                    keep_current = False
            except ValueError:
                # Si no parsea como fecha, por seguridad seguimos la decisión anterior
                pass
        
        if keep_current:
            new_lines.append(line)
            
    try:
        file_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        print(f"  -> Guardado. Líneas filtradas: {len(new_lines)} de {len(lines)}")
    except Exception as e:
        print(f"Error escribiendo {file_path.name}: {e}")

def main():
    if not LOGS_DIR.exists():
        print(f"El directorio de logs no existe: {LOGS_DIR}")
        return
        
    for log_file in LOGS_DIR.glob("*.log"):
        clean_log_file(log_file)

if __name__ == "__main__":
    main()
