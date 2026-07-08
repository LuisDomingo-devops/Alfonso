# Informe de Viabilidad: Delegación de TTS y STT al Cliente en Alfonso

## 1. Introducción

El presente informe evalúa la viabilidad técnica de trasladar las funcionalidades de Text-to-Speech (TTS) y Speech-to-Text (STT) del servidor de Alfonso al lado del cliente. El objetivo principal es reducir la carga computacional del servidor, mejorar la latencia percibida por el usuario y optimizar la escalabilidad del sistema, permitiendo que el servidor Alfonso se enfoque exclusivamente en la lógica de negocio y la entrega de respuestas en formato JSON.

## 2. Análisis de la Implementación Actual de Alfonso

Actualmente, el proyecto Alfonso centraliza el procesamiento de audio en el servidor. Las principales características de esta implementación son:

*   **TTS (Text-to-Speech):** Utiliza `edge-tts` como motor principal, con `pyttsx3` como fallback. El servidor genera archivos de audio MP3 y devuelve una URL para que el cliente los reproduzca. Esta lógica se encuentra en `app/tools/audio_tools.py` y es invocada por los endpoints de la API en `app/api/routes.py`.
*   **STT (Speech-to-Text):** Emplea `whisper` para la transcripción de audio, con un fallback a `speech_recognition` (que a su vez usa una versión `tiny` de Whisper). El cliente envía fragmentos de audio (bytes) al servidor, que realiza la transcripción y devuelve el texto. La funcionalidad de `wake word` también se basa en la transcripción en el servidor.
*   **Acoplamiento:** Aunque la lógica de audio está modularizada en `audio_tools.py`, los endpoints de la API (`/audio/command`, `/audio/wakeword/upload`) en `app/api/routes.py` integran directamente la ejecución de comandos con la generación de TTS, lo que implica que el servidor espera el resultado del orquestador para luego generar el audio de respuesta.

Esta arquitectura, si bien funcional, introduce latencia debido a la transferencia de audio y el procesamiento intensivo en el servidor, especialmente con modelos de STT como Whisper, que pueden consumir recursos significativos.

## 3. Viabilidad de la Delegación al Cliente

La delegación de las funcionalidades de TTS y STT al cliente es **altamente viable** y representa una mejora significativa en la arquitectura de Alfonso. Existen múltiples tecnologías maduras y eficientes que permiten realizar estas operaciones directamente en aplicaciones de escritorio o móviles nativas, eliminando la necesidad de que el servidor procese el audio.

### Beneficios Clave:

*   **Reducción de Carga del Servidor:** Libera al servidor de tareas computacionalmente intensivas, permitiéndole escalar de manera más eficiente y enfocarse en la lógica de negocio.
*   **Mejora de Latencia:** El procesamiento de audio se realiza localmente, eliminando los tiempos de ida y vuelta al servidor y resultando en una experiencia de usuario más fluida y reactiva.
*   **Privacidad:** El audio del usuario no necesita ser enviado a un servidor externo para su procesamiento, lo que puede ser un factor importante para la privacidad.
*   **Flexibilidad:** Permite al cliente elegir el motor de TTS/STT más adecuado según sus capacidades de hardware, preferencias de idioma o requisitos de calidad.

## 4. Tecnologías Cliente-Side para TTS y STT (Aplicaciones Nativas)

Para aplicaciones nativas (escritorio o móvil), existen APIs y bibliotecas específicas que ofrecen un rendimiento y una integración óptimos, con especial atención al consumo de recursos:

### 4.1. STT: Vosk y PocketSphinx (Bajo Consumo de RAM)

Para entornos con recursos de hardware limitados, **Vosk** y **PocketSphinx** son opciones excelentes para el reconocimiento de voz. Ambos están diseñados para funcionar offline y con un consumo mínimo de RAM.

*   **Vosk:** Ofrece modelos de reconocimiento de voz que pueden funcionar con tan solo **50MB de RAM** y modelos de lenguaje de pocos megabytes. Es conocido por su eficiencia y capacidad de operar en tiempo real en dispositivos con recursos limitados [1] [2]. Aunque su precisión puede ser ligeramente inferior a la de Whisper en algunos escenarios, su bajo consumo lo hace ideal para clientes ligeros.
*   **PocketSphinx:** Parte del proyecto CMU Sphinx, es un reconocedor de voz pequeño y ligero, diseñado específicamente para dispositivos embebidos y entornos con recursos limitados. Su consumo de RAM es muy bajo, lo que lo convierte en una opción viable para aplicaciones de escritorio con requisitos estrictos de memoria [3] [4].

**Ventajas:** Muy bajo consumo de RAM, procesamiento offline, buena velocidad, ideal para hardware limitado.
**Desventajas:** La precisión puede ser menor que la de modelos más grandes como Whisper, la calidad de los modelos de lenguaje puede variar.

### 4.2. STT: Whisper.cpp (Equilibrio entre Precisión y Eficiencia)

[Whisper.cpp][5] es una reimplementación en C/C++ del modelo Whisper de OpenAI, optimizada para eficiencia y ejecución local. Permite realizar transcripciones de voz a texto de alta calidad directamente en el dispositivo del usuario, sin necesidad de conexión a internet ni de enviar audio a un servidor externo. Aunque consume más RAM que Vosk (aproximadamente 150-200MB para modelos `tiny` o `base`), ofrece una precisión significativamente mayor [6] [7].

**Ventajas:** Alta precisión, procesamiento offline, baja latencia, eficiencia en recursos (comparado con la versión original de Python), amplia compatibilidad con lenguajes de programación a través de bindings.
**Desventajas:** Mayor consumo de RAM que Vosk, requiere la descarga inicial de modelos de lenguaje.

### 4.3. TTS: APIs Nativas del Sistema Operativo y eSpeak-ng (Bajo Consumo de RAM)

Para la síntesis de voz con bajo consumo de recursos, las APIs nativas del sistema operativo y `eSpeak-ng` son las opciones más eficientes:

*   **APIs Nativas del Sistema Operativo:** Utilizar las funcionalidades de TTS integradas en el sistema operativo (Windows, macOS, Linux, Android, iOS) es la opción más eficiente en términos de RAM, ya que el motor de síntesis ya está cargado o gestionado por el propio SO. Esto elimina la necesidad de cargar modelos adicionales en la aplicación cliente.
*   **eSpeak-ng:** Es un sintetizador de voz compacto y de código abierto que consume muy pocos recursos. Aunque su calidad de voz es más robótica en comparación con otros motores modernos, su eficiencia y bajo consumo de RAM lo hacen ideal para entornos donde la prioridad es la ligereza [8].

**Ventajas:** Mínimo o nulo consumo de RAM adicional, procesamiento offline, integración nativa (APIs del SO), muy rápido.
**Desventajas:** Calidad de voz básica (eSpeak-ng), dependencia del sistema operativo (APIs nativas).

### 4.4. TTS: Piper TTS (Equilibrio entre Calidad y Eficiencia)

[Piper TTS][9] es un motor de Text-to-Speech de alta calidad que se puede ejecutar de forma nativa en diversas plataformas. Para clientes con recursos limitados, se pueden utilizar **modelos cuantizados** de Piper, que reducen significativamente el consumo de RAM (alrededor de 100MB) manteniendo una calidad de voz natural [10].

**Ventajas:** Alta calidad de voz, procesamiento offline, baja latencia, personalización de voces, modelos cuantizados para menor consumo de RAM.
**Desventajas:** Mayor consumo de RAM que eSpeak-ng o las APIs nativas, requiere la descarga de modelos de voz.

### 4.5. Sherpa-ONNX (Solución Integral con Opciones Ligeras)

[Sherpa-ONNX][11] es una biblioteca versátil que ofrece funcionalidades de Speech-to-Text, Text-to-Speech y reconocimiento de hablante, todo ello basado en ONNX Runtime y diseñado para funcionar sin conexión a internet. Permite el uso de modelos optimizados y ligeros, lo que lo hace adecuado para entornos con recursos limitados. Proporciona bindings para múltiples lenguajes de programación (C++, Python, Java, C#, etc.) y es compatible con diversas plataformas [12] [13].

**Ventajas:** Solución integral (STT/TTS), procesamiento offline, multiplataforma, buen rendimiento con modelos optimizados, flexibilidad de integración.
**Desventajas:** Requiere la descarga de modelos, la configuración inicial puede ser más compleja que el uso de APIs nativas del sistema operativo.

## 5. Arquitectura Propuesta

La nueva arquitectura propuesta para Alfonso se centraría en un modelo cliente-servidor donde el servidor actúa como un orquestador de lógica de negocio y el cliente maneja todo el procesamiento de audio. El flujo de interacción sería el siguiente:

```mermaid
graph TD
    A[Cliente (Aplicación Nativa)] -->|1. Graba Audio (STT)| B{Procesamiento STT en Cliente}
    B -->|2. Envía Texto (JSON)| C[Servidor Alfonso]
    C -->|3. Procesa Lógica de Negocio|
    C -->|4. Devuelve Texto de Respuesta (JSON)| A
    A -->|5. Sintetiza Audio (TTS)| D{Procesamiento TTS en Cliente}
    D -->|6. Reproduce Audio| A
```

**Detalle del Flujo:**

1.  **Cliente Graba Audio:** La aplicación nativa captura el audio del usuario utilizando las APIs del sistema operativo o bibliotecas de bajo nivel.
2.  **Procesamiento STT en Cliente:** La aplicación nativa transcribe el audio a texto utilizando Vosk, PocketSphinx, Whisper.cpp o las APIs nativas del sistema operativo.
3.  **Cliente Envía Texto al Servidor:** El cliente envía el texto transcrito al servidor Alfonso a través de un endpoint de API (e.g., `/command` o `/chat`) en formato JSON. Este JSON incluiría el texto del comando y cualquier metadato relevante (ID de sesión, etc.).
4.  **Servidor Procesa Lógica de Negocio:** El servidor Alfonso recibe el texto, lo procesa con su orquestador y ejecuta la lógica de negocio correspondiente (ejecución de herramientas, interacción con LLM, etc.).
5.  **Servidor Devuelve Texto de Respuesta:** El servidor Alfonso devuelve la respuesta al cliente en formato JSON, conteniendo únicamente el texto que debe ser verbalizado y cualquier otro dato relevante para la interfaz de usuario.
6.  **Cliente Sintetiza Audio:** El cliente recibe el texto de respuesta y lo convierte a voz utilizando eSpeak-ng, Piper TTS (modelos cuantizados) o las APIs nativas del sistema operativo.
7.  **Cliente Reproduce Audio:** El cliente reproduce el audio sintetizado al usuario.

## 6. Recomendaciones

Para implementar esta delegación, se recomienda lo siguiente:

1.  **Modificar Endpoints del Servidor:**
    *   Eliminar la lógica de TTS y STT de los endpoints `/audio/command` y `/audio/wakeword/upload` en `app/api/routes.py`.
    *   Crear o adaptar un endpoint (e.g., `/command` o `/chat`) que reciba directamente el texto del usuario y devuelva solo el texto de respuesta del orquestador.
    *   Asegurarse de que el JSON de respuesta del servidor sea lo suficientemente rico en información para que el cliente pueda decidir cómo presentarla (e.g., tipo de respuesta, acciones sugeridas, etc.).

2.  **Desarrollo del Cliente (Aplicación Nativa - Bajo Consumo de RAM):**
    *   **Para STT (prioridad bajo consumo):** Se recomienda **Vosk** o **PocketSphinx** por su mínima huella de RAM. Si la precisión es crítica y se dispone de un poco más de RAM, **Whisper.cpp** con modelos pequeños es una excelente alternativa.
    *   **Para TTS (prioridad bajo consumo):** Las **APIs nativas del sistema operativo** son la opción más eficiente. Si se requiere una solución multiplataforma y de muy bajo consumo, **eSpeak-ng** es la elección. Para una mejor calidad de voz con un consumo moderado, **Piper TTS con modelos cuantizados** es una buena opción.

3.  **Manejo de Errores y Fallbacks:** Implementar mecanismos robustos de manejo de errores en el cliente para situaciones donde el STT o TTS local falle (e.g., falta de permisos de micrófono, modelos no cargados).

4.  **Configuración de Voces:** Permitir al usuario seleccionar la voz de TTS preferida en el cliente, aprovechando las opciones disponibles en el sistema operativo o las bibliotecas de TTS.

## 7. Conclusión

La delegación de las funcionalidades de TTS y STT al cliente es una estrategia técnica sólida y viable para el proyecto Alfonso. Al trasladar el procesamiento de audio a una aplicación nativa y priorizar soluciones de bajo consumo de RAM, se optimizará el rendimiento y la escalabilidad del backend, y se mejorará la experiencia del usuario al reducir la latencia y aumentar la privacidad. Las tecnologías actuales en el lado del cliente ofrecen la flexibilidad y la calidad necesarias para llevar a cabo esta transición de manera efectiva, incluso en dispositivos con recursos limitados.

## 8. Referencias

[1] [Vosk vs Whisper Local: The Ultimate 2026 Guide to Self ... - Sinologic](https://www.sinologic.net/en/2026-05/vosk-vs-whisper-local-the-ultimate-2026-guide-to-self-hosted-speech-recognition-stt.html)
[2] [Top 8 open source STT options for voice applications in 2026 - AssemblyAI Blog](https://www.assemblyai.com/blog/top-open-source-stt-options-for-voice-applications)
[3] [cmusphinx/pocketsphinx: A small speech recognizer - GitHub](https://github.com/cmusphinx/pocketsphinx)
[4] [Introduction to Pocketsphinx for Voice Controled Applications - Instructables](https://www.instructables.com/Introduction-to-Pocketsphinx-for-Voice-Controled-A/)
[5] [ggml-org/whisper.cpp: Port of OpenAI's Whisper model in C/C++ - GitHub](https://github.com/ggml-org/whisper.cpp)
[6] [Local voice-to-text that doesn't phone home — whisper.cpp + llama ... - Reddit](https://www.reddit.com/r/selfhosted/comments/1r0jekr/local_voicetotext_that_doesnt_phone_home/)
[7] [Whisper STT Service - openHAB](https://www.openhab.org/addons/voice/whisperstt/)
[8] [Local text-to-speech on Raspberry Pi and Python - Ats - Medium](https://atsss.medium.com/local-text-to-speech-on-raspberry-pi-and-python-49a5933cdb06)
[9] [rhasspy/piper - Generating speech locally in the web browser - GitHub](https://github.com/rhasspy/piper/issues/352)
[10] [I built a WASM powered Text-to-Speech library that runs in ... - Reddit](https://www.reddit.com/r/javascript/comments/1dww246/i_built_a_wasm_powered_texttospeech_library_that/)
[11] [k2-fsa/sherpa-onnx: Speech-to-text ... - GitHub](https://github.com/k2-fsa/sherpa-onnx)
[12] [sherpa-onnx - crates.io: Rust Package Registry](https://crates.io/crates/sherpa-onnx)
[13] [sherpa-onnx — sherpa 1.3 documentation](https://k2-fsa.github.io/sherpa/onnx/index.html)
