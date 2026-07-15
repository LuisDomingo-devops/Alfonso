# Plan de Implementación: Clasificación Cronológica y Detección de Pago de Facturas

Este plan describe cómo estructurar el guardado cronológico de facturas, detectar automáticamente si han sido pagadas analizando nuevos correos (ej. confirmaciones de pago de bancos o empresas) y trasladar las facturas pagadas a un disco duro de respaldo en red (`G:\RESPALDO_ESCRITORIO\Personal\gastos`).

## Cambios Propuestos

### 1. Clasificación por Orden de Entrada (Nombre de Archivo Cronológico)
- Modificaremos la generación de nombres de archivo de facturas en `save_invoice_to_desktop(email)` para usar un prefijo de marca de tiempo completo en formato `YYYYMMDD_HHMM_`:
  - Formato nuevo: `YYYYMMDD_HHMM_Factura_{ID}.txt`
  - Esto garantiza que en el Explorador de Archivos de Windows, al ordenar por nombre, las facturas aparezcan ordenadas estrictamente por su orden de llegada.

### 2. Detección Automática de Pago y Traslado de Facturas
- Crearemos una rutina `check_and_process_payments(email)` que se ejecutará al recibir o clasificar nuevos correos electrónicos:
  1. **Detección de Pago**: Identificará correos de confirmación de pago mediante palabras clave (ej. "pago recibido", "recibo cargado", "hemos recibido el pago", "confirmación de pago", "pago completado", "transacción realizada").
  2. **Búsqueda del Archivo de Factura**: Al detectar un pago (ej. de Iberdrola), buscará el archivo `.txt` correspondiente a la factura pendiente en la carpeta activa (`C:\Users\luisd\Desktop\facturas pendientes` y sus subcarpetas).
  3. **Ruta de Respaldo (`G:\...`)**:
     - Ruta de respaldo en Windows: `G:\RESPALDO_ESCRITORIO\Personal\gastos`.
     - Ruta traducida en WSL: `/mnt/g/RESPALDO_ESCRITORIO/Personal/gastos`.
     - Si la carpeta de destino `/mnt/g/...` no está accesible (por ejemplo, si el disco G: no está montado en WSL), Alfonso intentará crearla o emitirá un aviso descriptivo sugiriendo el montaje de la unidad.
  4. **Traslado físico**: Moverá el archivo `.txt` de la factura pendiente a la carpeta de respaldo y actualizará el estado en la base de datos de correos local a "Leído" y clasificado como "Pagado".

---

## Plan de Verificación

### Pruebas Automatizadas
- Crear un test en `tests/test_mail_operations.py` que simule la recepción de un correo de factura (se guarda en la carpeta activa) seguido de la recepción de un correo de confirmación de pago del mismo proveedor, verificando que el archivo se traslada correctamente al directorio de gastos temporal simulado.

### Verificación Manual
- Clasificar un correo simulado de factura de Iberdrola y confirmar que se genera con el prefijo temporal en la carpeta activa.
- Clasificar un correo que diga *"Confirmación de pago de su factura de Iberdrola"* y verificar que el archivo de la factura se mueve automáticamente al directorio de respaldo en red G:.
