"""
job_agent.py — Agente especialista para analizar ofertas de empleo y auto-postularse rellenando formularios.
"""

import os
import json
import asyncio
from app.utils.logger import app_logger
from app.utils.paths import get_cv_path
from app.adapters.llm_client import OllamaClient

class JobAgent:
    def __init__(self):
        self.llm = OllamaClient()
        self.cv_path = get_cv_path()

    def _read_cv(self) -> str:
        """Lee el archivo cv.md si existe."""
        if os.path.exists(self.cv_path):
            try:
                with open(self.cv_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                app_logger.error(f"Error leyendo cv.md: {e}")
        return "Currículum no disponible."

    async def auto_apply(self, url: str) -> dict:
        """
        Navega a la URL de la oferta, analiza el formulario/cuestionario,
        rellena las respuestas basadas en el CV y envía la solicitud.
        """
        app_logger.info(f"[JobAgent] Iniciando postulación automática en: {url}")
        from app.tools.client.browser_tools import browser_navigate, _get_page
        
        # 1. Navegar a la página
        nav_res = await browser_navigate(url)
        if nav_res.get("status") == "error":
            return {"status": "error", "message": f"Error al navegar: {nav_res.get('message')}"}

        page = await _get_page()
        if not page or isinstance(page, dict):
            return {"status": "error", "message": "No se pudo obtener el control de la página."}

        # Dar un momento para cargar dinámicamente formularios
        await asyncio.sleep(3.0)

        # 2. Extraer los campos interactivos del formulario
        fields = await page.evaluate('''() => {
            const result = [];
            const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], textarea');
            inputs.forEach(input => {
                let labelText = "";
                if (input.id) {
                    const label = document.querySelector(`label[for="${input.id}"]`);
                    if (label) labelText = label.innerText;
                }
                if (!labelText) {
                    const parentLabel = input.closest('label');
                    if (parentLabel) labelText = parentLabel.innerText;
                }
                
                // Buscar algún texto descriptivo cercano si no hay label formal
                if (!labelText && input.parentElement) {
                    labelText = input.parentElement.innerText.split('\\n')[0];
                }

                // Generar selector CSS único razonable
                let selector = "";
                if (input.id) {
                    selector = `#${input.id}`;
                } else if (input.name) {
                    selector = `input[name="${input.name}"], textarea[name="${input.name}"]`;
                }

                result.push({
                    id: input.id || "",
                    name: input.name || "",
                    placeholder: input.placeholder || "",
                    labelText: labelText ? labelText.trim() : "",
                    type: input.type || "text",
                    selector: selector
                });
            });
            return result;
        }''')

        if not fields:
            app_logger.info("[JobAgent] No se detectaron campos de entrada en esta página.")
            return {"status": "ok", "message": "No se detectó ningún formulario rellenable en esta oferta."}

        app_logger.info(f"[JobAgent] Campos detectados: {len(fields)}")

        # 3. Consultar al LLM las respuestas adecuadas según el CV
        cv_text = self._read_cv()
        prompt = f"""Eres Alfonso, el asistente de auto-postulación de empleo de Luis J. Domingo.
Tienes la tarea de rellenar de forma precisa e inteligente el siguiente formulario de empleo utilizando los datos del currículum que se te proporciona.

Currículum de Luis J. Domingo:
\"\"\"
{cv_text}
\"\"\"

Campos del formulario detectados (lista JSON):
{json.dumps(fields, indent=2, ensure_ascii=False)}

Por favor, genera un objeto JSON válido donde las claves sean exactamente los "selector" de cada campo y los valores sean la respuesta que debe rellenarse.
- Si el campo te pide Nombre, pon: "Luis J. Domingo"
- Si pide Email, pon: "luisdomingogarcia79@gmail.com"
- Si pide Teléfono, pon: "+34 638 471 780"
- Si es una pregunta de desarrollo o test, responde de forma extremadamente profesional, redactando en primera persona como Luis y basándote fielmente en su experiencia en Python, Django y automatización descrita en su CV.

Responde ESTRICTAMENTE con el formato JSON:
{{
  "selector_del_campo_1": "valor a rellenar",
  "selector_del_campo_2": "valor a rellenar"
}}
"""

        try:
            raw_answers = await self.llm.generate(prompt, mode="raw")
            # Limpieza robusta del JSON
            start = raw_answers.find("{")
            end = raw_answers.rfind("}") + 1
            if start != -1 and end != -1:
                answers = json.loads(raw_answers[start:end])
            else:
                answers = {}
        except Exception as e:
            app_logger.error(f"[JobAgent] Error procesando respuestas con LLM: {e}")
            return {"status": "error", "message": "Error al procesar respuestas del formulario con el modelo."}

        # 4. Rellenar los campos en la página
        for selector, val in answers.items():
            if not selector or not val:
                continue
            try:
                app_logger.info(f"[JobAgent] Rellenando selector {selector} con valor: {val}")
                await page.fill(selector, str(val))
                await asyncio.sleep(0.5)
            except Exception as e:
                app_logger.warning(f"[JobAgent] No se pudo rellenar el campo {selector}: {e}")

        # 5. Buscar y hacer clic en el botón de postulación / enviar
        submit_selector = await page.evaluate('''() => {
            const btn = document.querySelector('button[type="submit"], input[type="submit"], button#submit, .submit-btn, button.submit, button#apply');
            if (btn) {
                if (btn.id) return `#${btn.id}`;
                if (btn.className) return `button.${btn.className.split(' ').filter(c => c).join('.')}`;
                return 'button[type="submit"]';
            }
            return null;
        }''')

        if submit_selector:
            try:
                app_logger.info(f"[JobAgent] Haciendo click en botón de enviar: {submit_selector}")
                # Click y espera de navegación corta
                await page.click(submit_selector)
                await asyncio.sleep(3.0)
                return {"status": "ok", "message": "Formulario rellenado y enviado automáticamente."}
            except Exception as e:
                app_logger.error(f"[JobAgent] Error al hacer clic en enviar: {e}")
                return {"status": "error", "message": f"Se rellenó el formulario pero falló el envío: {e}"}
        else:
            app_logger.info("[JobAgent] No se encontró un botón de enviar obvio.")
            return {"status": "ok", "message": "Formulario rellenado. No se encontró botón de enviar automático."}

job_agent = JobAgent()
