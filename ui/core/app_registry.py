"""
app_registry.py — Detecta y registra aplicaciones instaladas en Windows.

Escanea el sistema en busca de aplicaciones comunes, almacena sus rutas en un
archivo .env dinámico que se actualiza cada vez que se inicia el cliente.
"""

import os
import platform
import logging
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict
import winreg

logger = logging.getLogger(__name__)

# Rutas comunes donde Windows instala programas
_COMMON_INSTALL_PATHS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.expandvars(r"%ProgramFiles%"),
    os.path.expandvars(r"%ProgramFiles(x86)%"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
]

# Aplicaciones que buscamos automáticamente
_KNOWN_APPS = {
    "firefox": ["Firefox", "firefox.exe", "Mozilla Firefox"],
    "chrome": ["Chrome", "chrome.exe", "Google Chrome", "Google\\Chrome"],
    "edge": ["Edge", "msedge.exe", "Microsoft Edge"],
    "vscode": ["Code", "code.exe", "Visual Studio Code"],
    "notepad": ["Notepad", "notepad.exe"],
    "powershell": ["PowerShell", "pwsh.exe"],
    "vlc": ["VLC", "vlc.exe", "VideoLAN"],
    "7zip": ["7-Zip", "7z.exe"],
    "git": ["Git", "git.exe"],
    "python": ["Python", "python.exe"],
    "node": ["Node.js", "node.exe"],
    "spotify": ["Spotify", "Spotify.exe"],
    "discord": ["Discord", "Discord.exe"],
    "telegram": ["Telegram", "Telegram.exe"],
    "slack": ["Slack", "slack.exe"],
    "teams": ["Microsoft Teams", "Teams.exe"],
    "obs": ["OBS Studio", "obs64.exe"],
}


def _scan_common_paths() -> Dict[str, str]:
    """Escanea rutas comunes en busca de aplicaciones ejecutables."""
    found_apps = {}
    
    for app_name, search_patterns in _KNOWN_APPS.items():
        for base_path in _COMMON_INSTALL_PATHS:
            if not os.path.exists(base_path):
                continue
            
            try:
                for root, dirs, files in os.walk(base_path, topdown=True):
                    # Limitar profundidad para no ser tan lento
                    if root.count(os.sep) - base_path.count(os.sep) > 3:
                        dirs.clear()  # No descender más
                        continue
                    
                    for file in files:
                        file_lower = file.lower()
                        # Buscar exe de la app
                        for pattern in search_patterns:
                            if pattern.lower() in file_lower:
                                if file_lower.endswith(".exe"):
                                    full_path = os.path.join(root, file)
                                    # Validar que sea ejecutable
                                    if os.path.isfile(full_path):
                                        logger.info(f"✓ Encontrada: {app_name} → {full_path}")
                                        found_apps[app_name] = full_path
                                        # No seguir buscando para esta app
                                        dirs.clear()
                                        break
                    
                    if app_name in found_apps:
                        break
            
            except (PermissionError, OSError) as e:
                logger.debug(f"Acceso denegado a {base_path}: {e}")
                continue
            
            if app_name in found_apps:
                break
    
    return found_apps


def _scan_registry() -> Dict[str, str]:
    """Escanea el registro de Windows para encontrar rutas de aplicaciones."""
    found_apps = {}
    
    if platform.system() != "Windows":
        return found_apps
    
    try:
        # Ruta donde Windows almacena info de apps instaladas
        uninstall_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, uninstall_key) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        try:
                            display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                            install_location = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                            
                            display_name_lower = display_name.lower()
                            
                            # Buscar apps conocidas
                            for app_name, patterns in _KNOWN_APPS.items():
                                for pattern in patterns:
                                    if pattern.lower() in display_name_lower:
                                        # Buscar exe en el directorio
                                        if install_location and os.path.exists(install_location):
                                            # Búsqueda un poco más profunda para detectar exes en subcarpetas (como Edge)
                                            for root, dirs, files in os.walk(install_location):
                                                # Limitar profundidad para mantener rendimiento
                                                if root.count(os.sep) - install_location.count(os.sep) > 2:
                                                    dirs.clear()
                                                    continue
                                                for file in files:
                                                    file_l = file.lower()
                                                    if file_l.endswith(".exe") and any(p.lower() in file_l for p in patterns):
                                                        exe_path = os.path.join(root, file)
                                                        logger.info(f"✓ Registro (profundo): {app_name} → {exe_path}")
                                                        found_apps[app_name] = exe_path
                                                        dirs.clear()
                                                        break
                                                if app_name in found_apps:
                                                    break
                                        break
                        except (OSError, PermissionError):
                            continue
                except OSError:
                    continue
    
    except Exception as e:
        logger.warning(f"Error escaneando registro: {e}")
    
    return found_apps


def _scan_app_paths() -> Dict[str, str]:
    """Escanea 'App Paths' en el registro para encontrar rutas exactas de ejecutables."""
    found_apps = {}
    if platform.system() != "Windows":
        return found_apps

    try:
        # HKLM y HKCU son lugares comunes para App Paths
        for hkey in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            app_paths_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            try:
                with winreg.OpenKey(hkey, app_paths_key) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            exe_name = winreg.EnumKey(key, i)
                            exe_name_lower = exe_name.lower()
                            
                            for app_name, patterns in _KNOWN_APPS.items():
                                if any(p.lower() in exe_name_lower for p in patterns) and exe_name_lower.endswith(".exe"):
                                    with winreg.OpenKey(key, exe_name) as subkey:
                                        try:
                                            # El valor (Default) contiene la ruta completa al ejecutable
                                            path, _ = winreg.QueryValueEx(subkey, "")
                                            if path and os.path.exists(path) and os.path.isfile(path):
                                                found_apps[app_name] = path
                                                logger.info(f"✓ App Paths: {app_name} → {path}")
                                        except (OSError, FileNotFoundError):
                                            continue
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception as e:
        logger.debug(f"Error escaneando App Paths: {e}")
    return found_apps


def scan_installed_apps() -> Dict[str, str]:
    """Escanea el sistema en busca de aplicaciones instaladas."""
    logger.info("Escaneando aplicaciones instaladas...")
    
    apps = {}
    
    # Escanear rutas comunes (más exhaustivo)
    apps.update(_scan_common_paths())

    # Escanear registro (más preciso con búsqueda profunda)
    apps.update(_scan_registry())
    
    # Escanear App Paths (el método más fiable de Windows)
    apps.update(_scan_app_paths())
    
    logger.info(f"Se encontraron {len(apps)} aplicaciones: {list(apps.keys())}")
    return apps


def generate_env_content(apps: Dict[str, str]) -> str:
    """Genera contenido para el archivo .env con las rutas de aplicaciones."""
    lines = [
        "# Aplicaciones detectadas automáticamente",
        "# Generado por: app_registry.py",
        "# Última actualización: auto",
        "# Este archivo se regenera cada vez que se inicia el cliente\n",
    ]
    
    for app_name, exe_path in sorted(apps.items()):
        env_key = f"APP_{app_name.upper()}"
        # Escapar backslashes para Windows
        safe_path = exe_path.replace("\\", "\\\\")
        lines.append(f"{env_key}={safe_path}")
    
    # Agregar servidor por defecto si no existe
    lines.extend([
        "\n# Configuración del servidor Alfonso",
        "ALFONSO_SERVER_URL=ws://localhost:8765",
        "ALFONSO_SERVER=http://localhost:8000",
    ])
    
    return "\n".join(lines)


def update_app_registry(env_file: str = ".env.apps") -> Dict[str, str]:
    """
    Actualiza el archivo .env con las aplicaciones detectadas.
    
    Args:
        env_file: Ruta del archivo .env (default: .env.apps en el mismo directorio)
    
    Returns:
        Diccionario con las apps encontradas
    """
    logger.info(f"Actualizando registro de aplicaciones en: {env_file}")
    
    # Detectar aplicaciones
    apps = scan_installed_apps()
    
    # Generar contenido
    env_content = generate_env_content(apps)
    
    # Escribir archivo
    try:
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(env_content)
        logger.info(f"✓ Registro guardado en: {env_file}")
    except Exception as e:
        logger.error(f"Error guardando registro: {e}")
    
    return apps


def load_app_registry(env_file: str = ".env.apps") -> Dict[str, str]:
    """
    Carga el registro de aplicaciones desde el archivo .env.
    
    Args:
        env_file: Ruta del archivo .env
    
    Returns:
        Diccionario con app_name -> ruta
    """
    apps = {}
    
    if not os.path.exists(env_file):
        logger.warning(f"Archivo de registro no encontrado: {env_file}")
        return apps
    
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                
                # Ignorar comentarios y líneas vacías
                if not line or line.startswith("#"):
                    continue
                
                # Parsear línea
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Procesar variables de aplicaciones
                    if key.startswith("APP_"):
                        app_name = key[4:].lower()  # Quitar "APP_" y convertir a minúsculas
                        # Desescapar backslashes
                        app_path = value.replace("\\\\", "\\")
                        apps[app_name] = app_path
        
        logger.info(f"✓ Registro cargado: {len(apps)} apps")
        return apps
    
    except Exception as e:
        logger.error(f"Error cargando registro: {e}")
        return apps


def get_app_path(app_name: str, env_file: str = ".env.apps") -> Optional[str]:
    """Obtiene la ruta de una aplicación desde el registro."""
    apps = load_app_registry(env_file)
    return apps.get(app_name.lower())


def launch_app(app_name: str, env_file: str = ".env.apps") -> bool:
    """
    Busca una aplicación en el registro y la ejecuta en el host Windows.
    """
    app_path = get_app_path(app_name, env_file)
    
    if not app_path:
        logger.error(f"No se encontró la ruta para la aplicación: {app_name}")
        return False
        
    try:
        if platform.system() == "Windows":
            # os.startfile es la forma más limpia de lanzar apps en Windows 
            # sin bloquear el proceso de Python y manejando permisos correctamente.
            os.startfile(app_path)
            logger.info(f"🚀 Ejecutando {app_name} desde {app_path}")
            return True
        else:
            # Para otros sistemas (WSL puro o Linux)
            subprocess.Popen([app_path], start_new_session=True)
            return True
    except Exception as e:
        logger.error(f"Error al intentar abrir {app_name}: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Script de prueba
    print("=" * 60)
    print("Escaneando aplicaciones instaladas...")
    print("=" * 60)
    
    apps = update_app_registry(".env.apps")
    
    print("\n" + "=" * 60)
    print("Aplicaciones detectadas:")
    print("=" * 60)
    for app_name, exe_path in sorted(apps.items()):
        print(f"  {app_name:20} → {exe_path}")
    
    print("\n✓ Registro guardado en: .env.apps")
