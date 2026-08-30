"""
Real-time Telegram alerts (trade OPEN / trade CLOSE), separate from the
daily summary in telegram_bot.py.

Uses plain synchronous HTTP calls to Telegram's Bot API (requests), NOT
python-telegram-bot's async Application - engine.py's order-fill callbacks
run inside ib_insync's own asyncio event loop, and calling `await` there
directly would conflict with it. A simple synchronous HTTP POST sidesteps
that entirely and is the more robust choice for alerts fired from inside
IBKR event callbacks.
"""

import logging

import requests

from . import config

log = logging.getLogger("tsla_bot.alerts")

API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str):
    if config.TELEGRAM_BOT_TOKEN.startswith("REPLACE_WITH"):
        log.warning("Telegram not configured yet (config.py has placeholder token) - alert not sent:\n%s", text)
        return
    url = API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.post(
            url,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            log.error("Telegram alert failed: %s %s", resp.status_code, resp.text)
    except requests.RequestException:
        log.exception("Telegram alert failed (network error)")


def alert_trade_open(side, entry_price, stop, target, shares, risk_usd):
    text = (
        f"🟢 <b>TSLA {side} OPENED</b>\n"
        f"Entry: ${entry_price:.2f}\n"
        f"Stop: ${stop:.2f}  |  Target: ${target:.2f}\n"
        f"Shares: {shares}  |  Risk: ${risk_usd:.2f}"
    )
    _send(text)


def alert_trade_close(side, exit_price, reason, pnl_usd, pnl_pct, bars_held):
    emoji = "✅" if pnl_usd > 0 else ("❌" if pnl_usd < 0 else "➖")
    text = (
        f"{emoji} <b>TSLA {side} CLOSED</b> ({reason})\n"
        f"Exit: ${exit_price:.2f}\n"
        f"PnL: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)\n"
        f"Held: {bars_held} bars"
    )
    _send(text)


def alert_engine_error(message: str):
    """Optional: fire on unhandled engine exceptions, so the client knows
    the bot stopped rather than silently going dark."""
    _send(f"⚠️ <b>TSLA Bot error</b>\n{message}")
