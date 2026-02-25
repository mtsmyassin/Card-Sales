"""Bilingual message system and store constants."""

from config import Config

KNOWN_STORES = Config.STORES
_STORE_CHOICE = {str(i): s for i, s in enumerate(KNOWN_STORES, 1)}

MESSAGES: dict[str, dict[str, str]] = {
    "es": {
        "register_start": "Bienvenido a Carimas Bot. Ingresa tu usuario para registrarte:",
        "enter_password": "Contrasena:",
        "bad_credentials": "Usuario o contrasena incorrectos. Ingresa tu usuario:",
        "registered": "Registrado. Tienda: {store}.\nEnvia una foto del Reporte Z para comenzar.",
        "welcome_back": "Registrado en {store}. Envia la foto del Reporte Z.",
        "photo_send": "Envia la foto del Reporte Z.",
        "processing": "Procesando... por favor espera.",
        "ocr_date": (
            "Cual es la fecha del reporte Z?\nOCR: {date}\nEscribe la fecha (MM/DD/AAAA) o responde OK para confirmar."
        ),
        "ocr_reg": ("Numero de caja registradora?\nOCR: {reg}\nEscribe el numero o responde OK para confirmar."),
        "bad_date": "No se pudo leer la fecha. Usa MM/DD/AAAA (ej. 02/20/2026) o responde OK.",
        "bad_reg": "Ingresa un numero de caja (ej. 1) o responde OK para mantener el valor del OCR.",
        "yes_no": "Responde SI para guardar o NO para cancelar.",
        "saved": (
            "Guardado{photo_note}. Caja #{reg} -- ${gross:.2f} bruto.\n"
            "Si no lo ves en la app, selecciona el filtro 'Todos'."
        ),
        "cancelled": "Cancelado. Envia otra foto cuando estes listo.",
        "invalid_store": "Responde con 1, 2, 3, 4 o 5.",
        "store_confirm": "Tienda: {store}. Envia la foto del Reporte Z.",
        "store_prompt": (
            "Para cual tienda es este reporte?\n"
            + "\n".join(f"{i} -- {s}" for i, s in enumerate(Config.STORES, 1))
            + "\nResponde con el numero."
        ),
        "ocr_fail_retry": (
            "No se pudo leer el reporte.\n"
            "Consejos: sosten la camara directamente encima del recibo, "
            "con buena iluminacion y sin sombras. (Intento {attempt} de 2)"
        ),
        "ocr_fail_final": (
            "No se pudo procesar la foto despues de 2 intentos.\n"
            "Consejos:\n"
            "  - Superficie plana, camara directamente encima\n"
            "  - Buena iluminacion, sin flash directo\n"
            "  - Todo el recibo visible en la foto\n"
            "Ingresa este reporte manualmente en la app web."
        ),
        "null_retry": (
            "No se pudo leer: {fields}.\n"
            "Asegurate de que esas secciones del recibo esten visibles.\n"
            "Toma la foto mas cerca, con buena iluminacion y sin sombras. (Intento {attempt} de 2)"
        ),
        "null_final": (
            "No se pudo leer: {fields}.\n"
            "Fallo tras 2 intentos. Consejos:\n"
            "  - Coloca el recibo en una superficie plana\n"
            "  - Sosten la camara directamente encima\n"
            "  - Usa buena iluminacion, sin flash directo\n"
            "Ingresa este reporte manualmente en la app web."
        ),
        "photo_warn": "No se pudo subir la foto. El reporte se guardara sin ella.",
        "db_error": "Error guardando el reporte. Por favor ingresalo manualmente en la app web.",
        "photo_dl_error": "No se pudo descargar la foto. Intentalo de nuevo.",
        "photo_too_large": "La foto es demasiado grande (m\u00e1ximo 5 MB). Por favor env\u00eda una foto m\u00e1s peque\u00f1a.",
        "ocr_error": "Error procesando la imagen. Intentalo de nuevo.",
        "session_reset": (
            "Tu sesion fue restaurada despues de un reinicio del sistema.\n"
            "Por favor envia la foto del Reporte Z de nuevo."
        ),
        "help": (
            "Carimas Bot -- Ayuda\n\n"
            "Comandos disponibles:\n"
            "  /help      -- Ver esta ayuda\n"
            "  /status    -- Ver tu estado actual\n"
            "  /cancel    -- Cancelar la operacion en curso\n"
            "  /last      -- Ver el ultimo reporte enviado\n"
            "  /broadcast -- Enviar mensaje a todos (solo admin)\n\n"
            "Como enviar un Reporte Z:\n"
            "  1. Registrate con tu usuario y contrasena del sistema\n"
            "  2. Envia una foto clara y bien iluminada del Reporte Z\n"
            "  3. Confirma la fecha y numero de caja\n"
            "  4. Responde SI para guardar el reporte\n\n"
            "Asistente AI:\n"
            "  Toca 'Preguntar AI' para consultar datos de ventas y varianzas."
        ),
        "status_registered": (
            "Estado: Registrado\nTienda: {store}\nUsuario: {username}\nListo para recibir fotos de Reporte Z."
        ),
        "status_unregistered": ("Estado: No registrado\nEnvia cualquier mensaje para comenzar el registro."),
        "status_midflow": ("Estado: En proceso ({state})\nUsuario: {username}\nUsa /cancel para reiniciar."),
        "cancel_ok": "Operacion cancelada. Envia una foto del Reporte Z cuando estes listo.",
        "cancel_nothing": "No hay ninguna operacion activa en este momento.",
        "ai_welcome": (
            "Modo Asistente AI activado.\n\n"
            "Puedes preguntarme sobre ventas, varianzas, o cualquier dato de tu tienda.\n"
            "Ejemplos:\n"
            "  - Cuanto fue el bruto de ayer?\n"
            "  - Cual caja tiene mas varianza?\n"
            "  - Resume las ventas de esta semana\n\n"
            "Envia /cancel para salir del modo AI.\n"
            "Enviar una foto sigue funcionando normalmente."
        ),
        "ai_exit": "Modo AI desactivado. Envia una foto del Reporte Z cuando estes listo.",
        "payouts": (
            "Cuanto fue el total de payouts/desembolsos?\nEscribe el monto (ej. 50.00) o toca el boton si no hubo."
        ),
        "actual_cash": (
            "Cuanto efectivo hay en la caja?\nEscribe el monto contado, o toca Omitir para usar la varianza del OCR."
        ),
        "bad_amount": "Ingresa un monto valido (ej. 50.00 o 0).",
        "broadcast_confirm": ("Mensaje a enviar a {count} usuarios:\n\n{message}\n\nConfirmar envio?"),
        "broadcast_sent": "Mensaje enviado a {sent} de {total} usuarios.",
        "broadcast_cancelled": "Envio cancelado.",
        "broadcast_no_permission": "Solo administradores pueden usar /broadcast.",
        "error_connection": "Error de conexion. Intentalo de nuevo.",
        "error_state_expired": "Tu sesion expiro. Envia una foto para comenzar de nuevo.",
        "error_button_expired": "Este boton ya no es valido. Envia una foto para comenzar de nuevo.",
        "error_database": "Error de base de datos. Intentalo de nuevo.",
        "error_unknown": "Ocurrio un error inesperado. Intentalo de nuevo.",
        "lang_prompt": "Selecciona tu idioma / Select your language:",
        "lang_set": "Idioma configurado: Espanol.",
        "btn_ok": "OK",
        "btn_edit": "Corregir",
        "btn_save_yes": "SI Guardar",
        "btn_save_no": "NO Cancelar",
        "btn_no_payouts": "Sin payouts ($0)",
        "btn_skip": "Omitir",
        "btn_send": "Enviar",
        "btn_cancel": "Cancelar",
        "btn_ask_ai": "Preguntar AI",
        "preview_header": "Reporte Z leido:",
        "preview_register": "Caja: #{register}  |  Fecha: {date}",
        "preview_save_prompt": "Guardar este reporte? Responde SI o NO",
    },
    "en": {
        "register_start": "Welcome to Carimas Bot. Enter your username to register:",
        "enter_password": "Password:",
        "bad_credentials": "Invalid username or password. Enter your username:",
        "registered": "Registered. Store: {store}.\nSend a Z Report photo to get started.",
        "welcome_back": "Registered at {store}. Send the Z Report photo.",
        "photo_send": "Send the Z Report photo.",
        "processing": "Processing... please wait.",
        "ocr_date": ("What is the Z report date?\nOCR: {date}\nType the date (MM/DD/YYYY) or reply OK to confirm."),
        "ocr_reg": ("Register number?\nOCR: {reg}\nType the number or reply OK to confirm."),
        "bad_date": "Could not read the date. Use MM/DD/YYYY (e.g. 02/20/2026) or reply OK.",
        "bad_reg": "Enter a register number (e.g. 1) or reply OK to keep the OCR value.",
        "yes_no": "Reply YES to save or NO to cancel.",
        "saved": (
            "Saved{photo_note}. Register #{reg} -- ${gross:.2f} gross.\n"
            "If you don't see it in the app, select the 'All' filter."
        ),
        "cancelled": "Cancelled. Send another photo when ready.",
        "invalid_store": "Reply with 1, 2, 3, 4, or 5.",
        "store_confirm": "Store: {store}. Send the Z Report photo.",
        "store_prompt": (
            "Which store is this report for?\n"
            + "\n".join(f"{i} -- {s}" for i, s in enumerate(Config.STORES, 1))
            + "\nReply with the number."
        ),
        "ocr_fail_retry": (
            "Could not read the report.\n"
            "Tips: hold the camera directly above the receipt, "
            "with good lighting and no shadows. (Attempt {attempt} of 2)"
        ),
        "ocr_fail_final": (
            "Could not process the photo after 2 attempts.\n"
            "Tips:\n"
            "  - Flat surface, camera directly above\n"
            "  - Good lighting, no direct flash\n"
            "  - Entire receipt visible in the photo\n"
            "Enter this report manually in the web app."
        ),
        "null_retry": (
            "Could not read: {fields}.\n"
            "Make sure those sections of the receipt are visible.\n"
            "Take the photo closer, with good lighting and no shadows. (Attempt {attempt} of 2)"
        ),
        "null_final": (
            "Could not read: {fields}.\n"
            "Failed after 2 attempts. Tips:\n"
            "  - Place the receipt on a flat surface\n"
            "  - Hold the camera directly above\n"
            "  - Use good lighting, no direct flash\n"
            "Enter this report manually in the web app."
        ),
        "photo_warn": "Could not upload the photo. The report will be saved without it.",
        "db_error": "Error saving the report. Please enter it manually in the web app.",
        "photo_dl_error": "Could not download the photo. Please try again.",
        "photo_too_large": "Photo is too large (max 5 MB). Please send a smaller photo.",
        "ocr_error": "Error processing the image. Please try again.",
        "session_reset": ("Your session was restored after a system restart.\nPlease send the Z Report photo again."),
        "help": (
            "Carimas Bot -- Help\n\n"
            "Available commands:\n"
            "  /help      -- Show this help\n"
            "  /status    -- Show your current status\n"
            "  /cancel    -- Cancel the current operation\n"
            "  /last      -- Show the last submitted report\n"
            "  /broadcast -- Send a message to everyone (admin only)\n\n"
            "How to submit a Z Report:\n"
            "  1. Register with your system username and password\n"
            "  2. Send a clear, well-lit photo of the Z Report\n"
            "  3. Confirm the date and register number\n"
            "  4. Reply YES to save the report\n\n"
            "AI Assistant:\n"
            "  Tap 'Ask AI' to query sales data and variances."
        ),
        "status_registered": (
            "Status: Registered\nStore: {store}\nUser: {username}\nReady to receive Z Report photos."
        ),
        "status_unregistered": ("Status: Not registered\nSend any message to start registration."),
        "status_midflow": ("Status: In progress ({state})\nUser: {username}\nUse /cancel to reset."),
        "cancel_ok": "Operation cancelled. Send a Z Report photo when ready.",
        "cancel_nothing": "No active operation at this time.",
        "ai_welcome": (
            "AI Assistant mode activated.\n\n"
            "You can ask me about sales, variances, or any data from your store.\n"
            "Examples:\n"
            "  - What was yesterday's gross?\n"
            "  - Which register has the most variance?\n"
            "  - Summarize this week's sales\n\n"
            "Send /cancel to exit AI mode.\n"
            "Sending a photo still works normally."
        ),
        "ai_exit": "AI mode deactivated. Send a Z Report photo when ready.",
        "payouts": (
            "What was the total payouts amount?\nType the amount (e.g. 50.00) or tap the button if there were none."
        ),
        "actual_cash": (
            "How much cash is in the drawer?\nType the counted amount, or tap Skip to use the OCR variance."
        ),
        "bad_amount": "Enter a valid amount (e.g. 50.00 or 0).",
        "broadcast_confirm": ("Message to send to {count} users:\n\n{message}\n\nConfirm send?"),
        "broadcast_sent": "Message sent to {sent} of {total} users.",
        "broadcast_cancelled": "Broadcast cancelled.",
        "broadcast_no_permission": "Only administrators can use /broadcast.",
        "error_connection": "Connection error. Please try again.",
        "error_state_expired": "Your session expired. Send a photo to start again.",
        "error_button_expired": "This button is no longer valid. Send a photo to start again.",
        "error_database": "Database error. Please try again.",
        "error_unknown": "An unexpected error occurred. Please try again.",
        "lang_prompt": "Selecciona tu idioma / Select your language:",
        "lang_set": "Language set: English.",
        "btn_ok": "OK",
        "btn_edit": "Edit",
        "btn_save_yes": "YES Save",
        "btn_save_no": "NO Cancel",
        "btn_no_payouts": "No payouts ($0)",
        "btn_skip": "Skip",
        "btn_send": "Send",
        "btn_cancel": "Cancel",
        "btn_ask_ai": "Ask AI",
        "preview_header": "Z Report read:",
        "preview_register": "Register: #{register}  |  Date: {date}",
        "preview_save_prompt": "Save this report? Reply YES or NO",
    },
}


def msg(telegram_id: int, key: str, **fmt) -> str:
    """Return a message string in the user's preferred language."""
    from telegram.session import _bot_state_lock, bot_state

    with _bot_state_lock:
        state = bot_state.get(telegram_id, {})
    lang = state.get("lang", "es")
    template = MESSAGES.get(lang, MESSAGES["es"]).get(key, key)
    return template.format(**fmt) if fmt else template
