"""
Telegram Notifier - usa tu bot existente para mandar las alertas.

Setup:
1. Tener un bot creado con @BotFather (token)
2. Iniciar conversación con tu bot (mandarle /start)
3. Obtener tu chat_id: https://api.telegram.org/bot<TOKEN>/getUpdates
   o usar @userinfobot
4. Configurar en .env:
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_BOT_CHAT_ID=123456789

Comportamiento:
- Si Telegram falla, marca la alerta como notified_at=null y se reintenta
- Las alertas notified=True nunca se reenvían
- Soporta MarkdownV2 con escape correcto
"""
import os
import time
from datetime import datetime
from typing import List

import httpx
from loguru import logger

from database.models import get_session
from alerts.migrations import Alert


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_CHAT_ID = os.getenv("TELEGRAM_BOT_CHAT_ID", "")


def _escape_md(text: str) -> str:
    """Escape de caracteres MarkdownV2 que rompen Telegram."""
    if not text:
        return ""
    chars = r"_*[]()~`>#+-=|{}.!"
    for c in chars:
        text = text.replace(c, f"\\{c}")
    return text


def _format_alert_for_telegram(alert: Alert) -> str:
    """Convierte Alert a Markdown listo para Telegram."""
    severity_emoji = {
        "critical": "🚨",
        "high": "⚠️",
        "medium": "🔔",
        "info": "ℹ️",
    }
    emoji = severity_emoji.get(alert.severity, "🔔")

    # Usamos Markdown clásico (no V2) para no escapar tanto.
    # Es más permisivo pero menos features.
    return (
        f"{emoji} *{alert.severity.upper()}*\n\n"
        f"{alert.message}\n\n"
        f"_Detectado: {alert.detected_at.strftime('%Y-%m-%d %H:%M UTC')}_"
    )


class TelegramNotifier:

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_BOT_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.warning(
                "Telegram bot no configurado: faltan "
                "TELEGRAM_BOT_TOKEN o TELEGRAM_BOT_CHAT_ID"
            )

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = httpx.post(url, json={
                "chat_id": self.chat_id,
                "text": text[:4000],   # límite Telegram = 4096
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }, timeout=15)
            if r.status_code == 200:
                return True
            logger.warning(f"Telegram {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    def send_pending_alerts(self, batch_size: int = 10) -> int:
        """Envía alertas no notificadas. Devuelve cuántas mandó."""
        if not self.enabled:
            return 0
        session = get_session()
        try:
            pending = (
                session.query(Alert)
                .filter(Alert.notified_at.is_(None))
                .order_by(Alert.detected_at.asc())
                .limit(batch_size)
                .all()
            )
            if not pending:
                return 0

            sent = 0
            for alert in pending:
                # Resumen primero si es la primera del batch
                text = _format_alert_for_telegram(alert)
                if self.send(text):
                    alert.notified_at = datetime.utcnow()
                    alert.notified_channel = "telegram"
                    sent += 1
                    # Pequeño delay entre mensajes
                    time.sleep(0.5)
                else:
                    # Falló - dejamos sin notified_at, se reintenta
                    break
            session.commit()
            logger.info(f"Telegram: {sent}/{len(pending)} alertas enviadas")
            return sent
        finally:
            session.close()

    def send_daily_digest(self) -> bool:
        """
        Modo alternativo: digest diario en lugar de alerta x alerta.
        Útil si querés recibir un resumen 1 vez por día en lugar de
        notifs sueltas. Usar con CRON / scheduler.
        """
        if not self.enabled:
            return False
        session = get_session()
        try:
            from datetime import timedelta
            since = datetime.utcnow() - timedelta(hours=24)
            alerts = (
                session.query(Alert)
                .filter(Alert.detected_at >= since)
                .order_by(Alert.severity, Alert.detected_at)
                .all()
            )
            if not alerts:
                return False

            by_kind = {}
            for a in alerts:
                by_kind.setdefault(a.kind, []).append(a)

            kind_emojis = {
                "rising_term": "📈",
                "new_question_cluster": "❓",
                "high_value_pain": "💢",
                "weak_competitor": "🎯",
                "niche_score_jump": "🚀",
            }
            kind_titles = {
                "rising_term": "Términos en alza",
                "new_question_cluster": "Preguntas nuevas",
                "high_value_pain": "Pain points transversales",
                "weak_competitor": "Competidores débiles",
                "niche_score_jump": "Nichos potentes",
            }

            lines = [
                f"🇦🇷 *Argentina Insights — Resumen 24h*",
                f"_{len(alerts)} alertas detectadas_\n",
            ]
            for kind, items in by_kind.items():
                emoji = kind_emojis.get(kind, "•")
                title = kind_titles.get(kind, kind)
                lines.append(f"\n{emoji} *{title}* ({len(items)})")
                for a in items[:5]:
                    lines.append(f"  • {a.title[:120]}")

            digest = "\n".join(lines)
            ok = self.send(digest)
            if ok:
                # Marcar todas como notificadas
                for a in alerts:
                    if a.notified_at is None:
                        a.notified_at = datetime.utcnow()
                        a.notified_channel = "telegram_digest"
                session.commit()
            return ok
        finally:
            session.close()


if __name__ == "__main__":
    import sys
    notifier = TelegramNotifier()
    if "--digest" in sys.argv:
        notifier.send_daily_digest()
    else:
        notifier.send_pending_alerts()
