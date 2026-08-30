"""
Telegram integration for the TSLA bot, per client's spec:
  "In the daily Telegram summary, in addition to the message, the bot
   attaches that day's CSV as a file... Also give me access to the
   cumulative master CSV (shared folder, or a Telegram command like /export)."

Two pieces:
  1. send_daily_summary() - called once/day (see config.DAILY_SUMMARY_TIME_ET),
     posts a short text summary + attaches that day's CSV.
  2. /export command - sends the master CSV on demand.

SETUP NEEDED (not done yet - placeholders in config.py):
  1. Message @BotFather on Telegram, /newbot, follow prompts, get a token.
  2. Message your new bot once (any text) so it can find your chat.
  3. Get your chat_id: visit https://api.telegram.org/bot<TOKEN>/getUpdates
     after step 2, look for "chat":{"id": ...}
  4. Fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID into config.py.
"""

import csv
import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from . import config

log = logging.getLogger("tsla_bot.telegram")


def _summarize_day(date_str: str) -> str:
    """Builds the daily text summary from that day's CSV."""
    path = config.DAILY_CSV_PATTERN.format(date=date_str)
    if not os.path.exists(path):
        return f"No activity logged for {date_str}."

    with open(path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    entries = [r for r in rows if r["tipo_decision"] == "ENTRY"]
    no_entry = [r for r in rows if r["tipo_decision"] == "NO-ENTRY"]
    no_setup = [r for r in rows if r["tipo_decision"] == "NO-SETUP"]
    closed = [r for r in entries if r["resultado"]]
    wins = [r for r in closed if r["resultado"] == "WIN"]

    # Count NO-ENTRY by blocking reason - useful at a glance
    reasons = {}
    for r in no_entry:
        reasons[r["filtro_bloqueador"]] = reasons.get(r["filtro_bloqueador"], 0) + 1
    reasons_str = ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1]))

    pnl_total = sum(float(r["pnl_usd"]) for r in closed if r["pnl_usd"])

    lines = [
        f"📊 TSLA Bot - {date_str}",
        f"Total decisions: {total}",
        f"ENTRY: {len(entries)} ({len(closed)} closed, {len(entries)-len(closed)} still open)",
        f"NO-ENTRY: {len(no_entry)}  [{reasons_str}]" if reasons_str else f"NO-ENTRY: {len(no_entry)}",
        f"NO-SETUP: {len(no_setup)}",
    ]
    if closed:
        wr = len(wins) / len(closed) * 100
        lines.append(f"Closed trades: {len(closed)} | Win rate: {wr:.1f}% | Net PnL: ${pnl_total:+.2f}")

    return "\n".join(lines)


async def send_daily_summary(bot, date_str: str = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    text = _summarize_day(date_str)
    await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)

    csv_path = config.DAILY_CSV_PATTERN.format(date=date_str)
    if os.path.exists(csv_path):
        with open(csv_path, "rb") as f:
            await bot.send_document(
                chat_id=config.TELEGRAM_CHAT_ID,
                document=f,
                filename=os.path.basename(csv_path),
            )
    else:
        log.warning("No daily CSV found for %s, skipping attachment.", date_str)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /export - sends the cumulative master CSV on demand."""
    if not os.path.exists(config.MASTER_CSV):
        await update.message.reply_text("No master CSV found yet.")
        return
    with open(config.MASTER_CSV, "rb") as f:
        await update.message.reply_document(document=f, filename="tsla_decisiones_master.csv")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /status - quick text summary of today so far."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    await update.message.reply_text(_summarize_day(date_str))


def build_app():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("status", cmd_status))
    return app


if __name__ == "__main__":
    # Runs the bot's command listener (for /export, /status) as a standalone
    # process. The daily summary itself should be triggered by a scheduler
    # (cron, or a scheduled task inside engine.py) calling send_daily_summary()
    # at config.DAILY_SUMMARY_TIME_ET - not wired to a scheduler here yet.
    app = build_app()
    log.info("Telegram bot listening for /export and /status...")
    app.run_polling()
