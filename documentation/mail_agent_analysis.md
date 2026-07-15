# Análisis de Capacidades: Agente de Correo Alfonso

Este documento presenta una auditoría de las herramientas actuales del agente de correo de Alfonso y realiza un análisis de brechas (gap analysis) detallando qué capacidades adicionales le faltan para operar de manera autónoma y fluida como un asistente humano de confianza.

---

## 1. Herramientas Actuales del Agente

Actualmente, Alfonso cuenta con las siguientes **12 herramientas** funcionales:

| Herramienta | Función Principal | Tipo |
| :--- | :--- | :--- |
| `mail_open_ui` / `mail_close_ui` | Controla la visualización del cliente de correo MUTHUR MAIL en el escritorio. | Interfaz |
| `mail_list_emails` / `mail_get_email` | Lista y lee el contenido detallado de los correos locales o sincronizados. | Consulta |
| `mail_receive_mock_emails` | Inyecta correos de prueba simulados (utilidad de desarrollo). | Sistema |
| `mail_classify_emails` | Clasifica la categoría, importancia y genera un resumen por IA de forma automatizada. | Análisis |
| `mail_get_unread_summary` | Genera un resumen matutino con tono humano de los correos urgentes y cotidianos. | Análisis |
| `mail_send_email` | Envía un correo electrónico (mediante SMTP real si está configurado). | Acción |
| `mail_delete_email` | Elimina un correo de la base de datos y refresca la UI. | Acción |
| `mail_reply_email` | Envía una respuesta formal a un correo existente. | Acción |
| `mail_forward_email` | Reenvía el contenido de un correo a un tercero. | Acción |
| `mail_generate_draft` | Genera borradores inteligentes de respuesta (delegando a un Abogado Experto si es `legal`). | Inteligencia |

---

## 2. Capacidades Faltantes para un Comportamiento Humano

Para que Alfonso actúe realmente como un **asistente ejecutivo humano de alto nivel**, necesita evolucionar de un sistema *reactivo* (que solo actúa cuando se le pregunta) a uno *proactivo y autónomo*. Las siguientes herramientas y capacidades serían necesarias:

### A. Gestión de Bandeja y Respuestas
1.  **Bandeja de Borradores Pendientes (`mail_save_draft_for_review`)**:
    *   *Concepto*: Un asistente humano nunca envía correos delicados sin que su jefe los revise. El agente debería poder generar respuestas sugeridas y guardarlas en una carpeta especial de "Borradores pendientes de aprobación" dentro de la interfaz para que el usuario solo tenga que pulsar *Aprobar y Enviar*.
2.  **Desuscripción Automática (`mail_unsubscribe_newsletter`)**:
    *   *Concepto*: Identificar correos basura/boletines (ej. Zara) y buscar y hacer click de forma autónoma en el enlace de desuscripción ("Unsubscribe") o enviar una petición automática de baja.

### B. Monitoreo Activo y Proactividad
3.  **Monitoreo en Segundo Plano (Cron Job)**:
    *   *Concepto*: En lugar de esperar a que abras la app para sincronizar Gmail, el agente debería ejecutarse cada 10-15 minutos en segundo plano de forma silenciosa.
4.  **Notificación de Urgencias Críticas (`mail_push_urgent_alert`)**:
    *   *Concepto*: Si llega un correo de alta importancia (ej. una citación judicial, notificación de Hacienda o una caída de servidor), el asistente debería interrumpir proactivamente (mediante un popup en el escritorio o un aviso por voz) diciendo: *"Luis, disculpa que te interrumpa, pero acabas de recibir una notificación urgente del Juzgado sobre Calle Mayor"*.

### C. Automatización de Flujos Derivados (Workflow Connection)
5.  **Pre-rellenado de Acciones Relacionadas (`mail_extract_actionable_task`)**:
    *   *Concepto*: Si el correo contiene una factura de Iberdrola, además de avisarte, el agente debería preparar la tarea de pago o pre-completar el formulario de transferencia. Si contiene una propuesta de reunión, debería buscar huecos libres en tu agenda y proponerle tres opciones al remitente en el borrador de respuesta.
6.  **Archivado Inteligente Autónomo (`mail_archive_low_importance`)**:
    *   *Concepto*: Mandar automáticamente recibos confirmados de Amazon, newsletters leídas o spam a carpetas de archivo para mantener tu bandeja de entrada en *Inbox Zero*.
