"""Notificaciones por Telegram (opcionales).

Se activan definiendo TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID. Si no están
definidas, los avisos solo se muestran en el panel web.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


def notificar(mensaje: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": mensaje,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception:
        log.exception("No se pudo enviar la notificación de Telegram")
        return False
