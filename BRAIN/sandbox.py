import subprocess
import shutil
import tempfile
from pathlib import Path

def validate_patch(target_file_relative: str, raw_diff: str) -> dict:
    """
    Copia los archivos necesarios a un directorio temporal, aplica el parche
    y ejecuta pytest para verificar que los cambios no rompen el sistema.
    """
    workspace_root = Path(__file__).resolve().parent.parent
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # 1. Copiar directorios esenciales
        for item in ["app", "tests"]:
            src = workspace_root / item
            if src.exists():
                shutil.copytree(src, temp_path / item, symlinks=True)
                
        # Copiar archivos raíz si existen (como config, pytest.ini, etc.)
        for file_name in ["requirements.txt", "pytest.ini"]:
            src = workspace_root / file_name
            if src.exists():
                shutil.copy2(src, temp_path / file_name)
                
        # 2. Guardar el diff en un archivo
        patch_file = temp_path / "proposed_change.patch"
        patch_file.write_text(raw_diff, encoding="utf-8")
        
        # 3. Aplicar el parche usando git apply o patch
        applied = False
        error_msg = ""
        
        try:
            # Inicializar un repo git temporal para poder usar git apply
            subprocess.run(["git", "init"], cwd=temp_path, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=temp_path, check=True, capture_output=True)
            
            result = subprocess.run(
                ["git", "apply", "--verbose", "proposed_change.patch"],
                cwd=temp_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                applied = True
            else:
                error_msg = f"git apply failed:\nStdout: {result.stdout}\nStderr: {result.stderr}"
        except Exception as e:
            error_msg = f"git apply exception: {str(e)}"
            
        # Si falló git apply, intentamos con el comando 'patch'
        if not applied:
            try:
                target_absolute_temp = temp_path / target_file_relative
                result = subprocess.run(
                    ["patch", str(target_absolute_temp), "proposed_change.patch"],
                    cwd=temp_path,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    applied = True
                else:
                    error_msg += f"\npatch command failed:\nStdout: {result.stdout}\nStderr: {result.stderr}"
            except Exception as e:
                error_msg += f"\npatch command exception: {str(e)}"
                
        if not applied:
            return {
                "success": False,
                "stage": "apply_patch",
                "error": f"No se pudo aplicar el parche en el entorno temporal.\nDetalles:\n{error_msg}"
            }
            
        # 4. Ejecutar tests con pytest
        try:
            # Asegurar que pytest ejecute usando python -m pytest para evitar problemas de PATH/venv
            result = subprocess.run(
                ["python3", "-m", "pytest", "tests/"],
                cwd=temp_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "stage": "testing",
                    "output": result.stdout
                }
            else:
                return {
                    "success": False,
                    "stage": "testing",
                    "error": f"Fallo al ejecutar la suite de pruebas (pytest return code {result.returncode}):\nStdout: {result.stdout}\nStderr: {result.stderr}"
                }
        except Exception as e:
            return {
                "success": False,
                "stage": "testing",
                "error": f"Error al ejecutar pytest: {str(e)}"
            }
