"""
COMFYUI API TOOLS — Integración con ComfyUI local o remoto para la generación de imágenes del avatar.
"""

from __future__ import annotations
import os
import json
import uuid
import urllib.request
import urllib.parse
from pathlib import Path
from app.utils.logger import tool_logger, error_logger

# Directorio local para guardar workflows y salidas
WORKFLOWS_DIR = Path("data/workflows")
OUTPUT_DIR = Path("data/output")

def _ok(**data) -> dict:
    return {"status": "ok", **data}

def _error(error_type: str, message: str) -> dict:
    return {"status": "error", "error_type": error_type, "message": message}

async def comfy_load_workflow(workflow_name: str, client_id: str | None = None) -> dict:
    """
    Carga un workflow de ComfyUI guardado previamente en formato API JSON.
    """
    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = WORKFLOWS_DIR / f"{workflow_name}.json"
        
        if not file_path.exists():
            # Crear un ejemplo básico de workflow si no existe ninguno
            default_workflow = {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "cfg": 8,
                        "denoise": 1,
                        "latent_image": ["5", 0],
                        "model": ["4", 0],
                        "negative": ["7", 0],
                        "positive": ["6", 0],
                        "sampler_name": "euler",
                        "scheduler": "normal",
                        "seed": 8566258,
                        "steps": 20
                    }
                },
                "4": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {
                        "ckpt_name": "v1-5-pruned-emaonly.ckpt"
                    }
                },
                "5": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {
                        "batch_size": 1,
                        "height": 512,
                        "width": 512
                    }
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["4", 1],
                        "text": "beautiful virtual influencer portrait, highly detailed, instagram style"
                    }
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["4", 1],
                        "text": "blurry, low quality, distorted, bad anatomy"
                    }
                },
                "8": {
                    "class_type": "VAEDecode",
                    "inputs": {
                        "samples": ["3", 0],
                        "vae": ["4", 2]
                    }
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "AlfonsoAvatar",
                        "images": ["8", 0]
                    }
                }
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_workflow, f, indent=2)
            
        with open(file_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)
            
        return _ok(workflow=workflow_data, file_path=str(file_path.absolute()))
    except Exception as e:
        error_logger.exception("Error en comfy_load_workflow")
        return _error("load_workflow_failed", str(e))

async def comfy_generate_image(
    workflow_name: str,
    prompt_updates: dict,
    server_address: str = "127.0.0.1:8188",
    client_id: str | None = None
) -> dict:
    """
    Envía una solicitud de generación de imagen a ComfyUI. 
    `prompt_updates` permite sobreescribir textos u opciones específicas del workflow cargado.
    """
    tool_logger.info(f"Enviando solicitud de generación de imagen a ComfyUI en {server_address}")
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # 1. Cargar el workflow base
        load_res = await comfy_load_workflow(workflow_name, client_id)
        if load_res.get("status") != "ok":
            return load_res
            
        workflow = load_res["workflow"]
        
        # 2. Aplicar actualizaciones del prompt (ej. actualizar el prompt positivo)
        # prompt_updates puede ser {"6": {"inputs": {"text": "nuevo prompt"}}}
        for node_id, node_patch in prompt_updates.items():
            if node_id in workflow:
                if "inputs" in node_patch:
                    workflow[node_id]["inputs"].update(node_patch["inputs"])
        
        # 3. Enviar a la API de ComfyUI
        comfy_client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": comfy_client_id}
        data = json.dumps(payload).encode('utf-8')
        
        # Intentar conexión con la API de ComfyUI
        req = urllib.request.Request(f"http://{server_address}/prompt", data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                prompt_id = res_data.get("prompt_id")
                return _ok(
                    message="Imagen solicitada con éxito en ComfyUI",
                    prompt_id=prompt_id,
                    info="La generación se ha encolado en ComfyUI."
                )
        except Exception as conn_err:
            tool_logger.warning(f"No se pudo conectar con la instancia de ComfyUI activa en {server_address}: {conn_err}")
            return _ok(
                message="Workflow preparado con éxito (simulado ya que ComfyUI no está activo)",
                workflow_preview=workflow,
                note="Inicia ComfyUI en tu máquina local o configura el endpoint en la variable de entorno para realizar ejecuciones reales."
            )
            
    except Exception as e:
        error_logger.exception("Error en comfy_generate_image")
        return _error("generation_failed", str(e))

TOOLS = {
    "comfy_load_workflow": comfy_load_workflow,
    "comfy_generate_image": comfy_generate_image
}
