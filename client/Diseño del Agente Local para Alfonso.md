# Diseño del Agente Local para Alfonso

## 1. Introducción

Este documento detalla el diseño del agente local, un componente esencial para permitir que Alfonso (ejecutándose en WSL/servidor) interactúe con el entorno de escritorio del usuario (PC cliente). El agente local actuará como un puente, recibiendo comandos del servidor a través de WebSockets y ejecutándolos localmente, resolviendo así el problema de la separación de entornos.

## 2. Arquitectura General

La arquitectura se compone de dos elementos principales:

*   **Servidor Alfonso (WSL/Servidor)**: Contendrá un módulo WebSocket que actuará como puente, enviando comandos al agente local y recibiendo confirmaciones o resultados.
*   **Agente Local (PC Cliente)**: Un script Python ligero que se ejecutará en el PC del usuario, escuchando el servidor WebSocket, ejecutando los comandos recibidos y enviando respuestas.

```mermaid
graph TD
    A["Servidor Alfonso (WSL)"] -->|WebSocket| B("Agente Local Cliente")
    B -->|Ejecuta Comandos Locales| C["Sistema Operativo Cliente"]
    C -->|Feedback/Resultados| B
    B -->|WebSocket| A
```

## 3. Protocolo de Comunicación WebSocket

La comunicación entre el servidor Alfonso y el agente local se realizará a través de un protocolo JSON sobre WebSockets. Cada mensaje será un objeto JSON con una estructura definida para asegurar una interpretación correcta.

### 3.1. Mensajes del Servidor al Cliente (Comandos)

El servidor enviará comandos al cliente para que realice acciones específicas. La estructura general de un mensaje de comando será:

```json
{
    "id": "UUID_DEL_COMANDO",
    "action": "nombre_de_la_accion",
    "params": {
        "parametro1": "valor1",
        "parametro2": "valor2"
    }
}
```

**Campos:**

*   `id` (string): Un identificador único para cada comando, permitiendo al servidor rastrear la respuesta correspondiente.
*   `action` (string): El nombre de la acción que el agente local debe ejecutar. Ejemplos: `open_app`, `type_text`, `move_mouse`, `screenshot`.
*   `params` (object): Un diccionario de parámetros específicos para la acción. El contenido variará según la `action`.

**Ejemplos de Comandos:**

*   **Abrir una aplicación:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "action": "open_app",
        "params": {
            "command": "gedit"
        }
    }
    ```

*   **Escribir texto:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174001",
        "action": "type_text",
        "params": {
            "text": "Hola, mundo!"
        }
    }
    ```

*   **Mover el ratón:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174002",
        "action": "move_mouse",
        "params": {
            "x": 100,
            "y": 200
        }
    }
    ```

*   **Tomar una captura de pantalla:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174003",
        "action": "screenshot",
        "params": {
            "filename": "screenshot_1.png"
        }
    }
    ```

### 3.2. Mensajes del Cliente al Servidor (Respuestas)

El agente local enviará respuestas al servidor para confirmar la ejecución de un comando, reportar errores o devolver resultados (ej. una captura de pantalla).

```json
{
    "id": "UUID_DEL_COMANDO_ORIGINAL",
    "status": "success" | "error",
    "result": "datos_del_resultado" | null,
    "error": "mensaje_de_error" | null
}
```

**Campos:**

*   `id` (string): El identificador del comando original al que se está respondiendo.
*   `status` (string): Indica el resultado de la operación (`success` o `error`).
*   `result` (any): Datos opcionales del resultado de la acción (ej. la ruta de una captura de pantalla, o el contenido de un archivo).
*   `error` (string): Mensaje de error si `status` es `error`.

**Ejemplos de Respuestas:**

*   **Éxito al abrir una aplicación:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "status": "success",
        "result": "Aplicación gedit iniciada correctamente."
    }
    ```

*   **Error al ejecutar un comando:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174001",
        "status": "error",
        "error": "No se pudo encontrar el comando 'gedit'."
    }
    ```

*   **Captura de pantalla exitosa:**
    ```json
    {
        "id": "123e4567-e89b-12d3-a456-426614174003",
        "status": "success",
        "result": {
            "filename": "screenshot_1.png",
            "data": "BASE64_DE_LA_IMAGEN" 
        }
    }
    ```
    (Nota: Para imágenes grandes, se podría considerar subir el archivo a un servicio de almacenamiento y enviar solo la URL).

## 4. Arquitectura del Agente Local (Cliente)

El agente local será un script Python que realizará las siguientes funciones:

1.  **Conexión WebSocket**: Establecerá y mantendrá una conexión persistente con el servidor Alfonso.
2.  **Manejo de Mensajes**: Recibirá mensajes JSON del servidor, los parseará y determinará la acción a ejecutar.
3.  **Ejecución de Acciones**: Utilizará librerías Python como `subprocess` para ejecutar comandos del sistema operativo (abrir aplicaciones) y `pyautogui` para interactuar con el ratón, teclado y tomar capturas de pantalla.
4.  **Manejo de Errores**: Capturará excepciones durante la ejecución de comandos y enviará mensajes de error al servidor.
5.  **Envío de Respuestas**: Formateará y enviará las respuestas (éxito, error, resultados) de vuelta al servidor a través del WebSocket.

## 5. Arquitectura del Puente en el Servidor (Alfonso)

El servidor Alfonso necesitará un módulo que:

1.  **Servidor WebSocket**: Levantará un servidor WebSocket para aceptar conexiones del agente local.
2.  **Enrutamiento de Comandos**: Recibirá las intenciones del LLM (ej. `open_application(gedit)`) y las transformará en el formato de comando WebSocket para el agente local.
3.  **Manejo de Respuestas**: Recibirá las respuestas del agente local y las procesará, actualizando el estado de la tarea o informando al LLM.

## 6. Consideraciones de Seguridad

*   **Autenticación**: Se debe implementar un mecanismo de autenticación (ej. token) para asegurar que solo los agentes autorizados puedan conectarse al servidor y viceversa.
*   **Autorización**: El agente local solo debe ejecutar acciones permitidas. Se podría definir una lista blanca de comandos o un sistema de permisos.
*   **Encriptación**: La comunicación WebSocket debe ser encriptada (WSS) para proteger los datos en tránsito.

## 7. Próximos Pasos

1.  Implementar el servidor WebSocket en Alfonso.
2.  Implementar el agente local en Python.
3.  Crear scripts de instalación y configuración.
4.  Documentar el uso y despliegue.
