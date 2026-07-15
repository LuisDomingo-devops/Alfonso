# Walkthrough: Clasificación Cronológica y Procesamiento de Pagos en Red

Hemos integrado el guardado cronológico de facturas y el traslado automático de facturas pagadas a tu disco de red en el router.

## Cambios Realizados

1.  **Orden Cronológico de Facturas (`app/tools/server/mail_tools.py`)**:
    -   Modificado el nombre de los archivos de facturas guardados en la carpeta activa para incluir un prefijo de marca de tiempo completo: `YYYYMMDD_HHMM_Factura_{ID}.txt`.
    -   Esto asegura que los archivos aparezcan ordenados estrictamente por fecha y hora de llegada en el Explorador de Archivos de Windows.
2.  **Detección y Traslado de Facturas Pagadas (`app/tools/server/mail_tools.py`)**:
    -   Creada la rutina `check_and_process_payments(email)`.
    -   **Heurísticas de Pago**: Detecta correos con confirmaciones de pago (ej. *"hemos recibido el pago"*, *"pago confirmado"*, *"recibo cargado"*, etc.).
    -   **Traslado en Red**: Busca la factura pendiente del proveedor en la carpeta activa y la traslada físicamente a tu unidad de red en el router:
        `G:\RESPALDO_ESCRITORIO\Personal\gastos` (mapeada a `/mnt/g/RESPALDO_ESCRITORIO/Personal/gastos` en WSL).
    -   **Robustez / Fallback**: Si la unidad G: en red no está conectada o disponible en WSL, Alfonso creará una carpeta fallback en tu Escritorio (`C:\Users\luisd\Desktop\facturas pagadas`) para evitar pérdidas.
    -   Al finalizar, elimina la carpeta vacía del proveedor en la carpeta de pendientes para mantenerla limpia.

---

## Verificación

-   **Tests Unitarios**: Añadido `test_check_and_process_payments` en `tests/test_mail_operations.py`.
-   **Suite Completa**: Los 87 tests del proyecto corren y pasan al 100%.
