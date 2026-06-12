import subprocess
import platform
import re
import json
import sys

# Forzar salida en UTF-8 para evitar caracteres extraños en Windows
if sys.stdout.encoding != 'utf-8':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except Exception:
        pass

def get_linux_mics():
    try:
        sources_output = subprocess.check_output(["pactl", "list", "sources"], text=True)
        outputs_output = subprocess.check_output(["pactl", "list", "source-outputs"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Error: PulseAudio (pactl) no está disponible."

    mics = []
    source_blocks = sources_output.split("\n\n")
    for block in source_blocks:
        if "Name:" in block:
            name_match = re.search(r"Name: (.*)", block)
            desc_match = re.search(r"Description: (.*)", block)
            index_match = re.search(r"Source #(\d+)", block)
            
            if name_match and desc_match:
                name = name_match.group(1)
                desc = desc_match.group(1)
                index = index_match.group(1) if index_match else "?"
                
                # Palabras clave ampliadas para detección de integrados
                integrated_keywords = ["builtin", "built-in", "internal", "analog", "integrated", "intel", "smart sound", "realtek"]
                is_integrated = any(kw in desc.lower() or kw in name.lower() for kw in integrated_keywords)
                
                mics.append({
                    "index": index,
                    "name": name,
                    "description": desc,
                    "integrated": is_integrated,
                    "in_use_by": []
                })

    output_blocks = outputs_output.split("\n\n")
    for block in output_blocks:
        source_index_match = re.search(r"Source: (\d+)", block)
        app_name_match = re.search(r'application.name = "(.*?)"', block)
        
        if source_index_match and app_name_match:
            s_idx = source_index_match.group(1)
            app_name = app_name_match.group(1)
            for mic in mics:
                if mic["index"] == s_idx:
                    mic["in_use_by"].append(app_name)
    return mics

def get_windows_mics():
    # PowerShell con codificación UTF8 explícita
    ps_script = """
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $mics = Get-PnpDevice -Class AudioEndpoint -Status OK | Where-Object { $_.FriendlyName -like "*mic*" -or $_.FriendlyName -like "*entrada*" -or $_.FriendlyName -like "*Intel*" }
    $result = @()
    foreach ($mic in $mics) {
        # Intel Smart Sound y Realtek suelen ser los integrados en laptops modernas
        $isIntegrated = ($mic.FriendlyName -like "*Internal*" -or $mic.FriendlyName -like "*Built-in*" -or $mic.FriendlyName -like "*Realtek*" -or $mic.FriendlyName -like "*Intel*")
        $result += [PSCustomObject]@{
            Name = $mic.FriendlyName
            Integrated = $isIntegrated
        }
    }
    $result | ConvertTo-Json
    """
    try:
        # Usamos shell=True para Windows y capturamos en bytes para decodificar nosotros
        process = subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
        output = process.stdout.decode('utf-8', errors='replace')
        
        if not output.strip(): return []
        data = json.loads(output)
        if isinstance(data, dict): data = [data]
        
        mics = []
        for item in data:
            mics.append({
                "name": item["Name"],
                "integrated": item["Integrated"],
                "description": item["Name"],
                "in_use_by": []
            })
        return mics
    except Exception as e:
        return f"Error en Windows: {str(e)}"

def main():
    system = platform.system()
    print(f"--- Sistema detectado: {system} ---")
    
    if system == "Linux":
        mics = get_linux_mics()
    elif system == "Windows":
        mics = get_windows_mics()
    else:
        print("Este script está optimizado para Linux y Windows.")
        return

    if isinstance(mics, str):
        print(mics)
        return

    print("\nMicrófonos detectados:")
    print("-" * 60)
    
    found_meet_mic = False
    for mic in mics:
        # Limpieza de nombres para Windows
        clean_name = mic['description'].replace('¢', 'ó').replace('¡', 'í').replace('©', '©')
        
        status = "[INTEGRADO]" if mic["integrated"] else "[EXTERNO]"
        print(f"{status} {clean_name}")
        
        if mic["in_use_by"]:
            apps = ", ".join(mic["in_use_by"])
            print(f"   -> EN USO POR: {apps}")
            if any(browser in apps.lower() for browser in ["chrome", "chromium", "firefox", "edge", "google-chrome"]):
                print("   *** ESTE ES EL QUE PROBABLEMENTE USA GOOGLE MEET ***")
                found_meet_mic = True
        print("-" * 60)

    if system == "Windows":
        print("\nNota sobre Windows:")
        print("Debido a restricciones de privacidad, Windows no permite ver fácilmente qué app")
        print("usa el micro desde este script. Sin embargo, el que dice 'Intel Smart Sound'")
        print("es el integrado de tu laptop. Si estás en Meet, ese será el activo por defecto.")
    elif not found_meet_mic:
        print("\nNota: No se detectó ninguna aplicación usando el micro activamente.")

if __name__ == "__main__":
    main()
