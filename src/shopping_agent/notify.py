"""Telegram notifications (optional).

They are enabled by setting TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. If those
are not set, alerts are only shown in the web panel.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


def _send(message: str) -> tuple[bool, str]:
    """Sends the message. Returns (ok, detail) — the detail includes the error
    description given by the Telegram API (e.g. "chat not found")."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID sin configurar"
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 200 and data.get("ok"):
            return True, "enviado"
        return False, data.get("description") or f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.HTTPError as exc:
        return False, f"error de red: {exc}"


def send(message: str) -> bool:
    ok, detail = _send(message)
    if not ok and os.environ.get("TELEGRAM_BOT_TOKEN"):
        log.error("Telegram could not send the alert: %s", detail)
    return ok


def send_test() -> tuple[bool, str]:
    """Sends a test message and returns (ok, detail) for the panel."""
    return _send("✅ Prueba del agente de compras: las notificaciones funcionan.")
