# TSLA Paper Trading Bot

Live paper-trading engine for the client's 3-Factor TSLA strategy, built
around the validated `tsla_3factor_CORRECTED.py` signal logic, with:
- Per-decision CSV logging (ENTRY / NO-ENTRY+reason / NO-SETUP), per
  `Spec_Logging_CSV_TSLA_EN.docx`
- risk_pct position sizing (1%, per client instruction for this phase)
- Bracket order execution (market entry + OCA stop/limit)
- Telegram daily summary + CSV attachment, `/export` and `/status` commands
- A fresh Streamlit dashboard built for the decision-log schema

## Status: built, syntax-checked, and unit-tested against synthetic data.
## NOT yet live-tested against a real IBKR bar stream. Same caveat as the
## Gold bot: paper-test carefully before trusting this unattended, especially:
- The exact live entry-price approximation (see NOTE in `engine.py`'s
  `open_new_position()` - backtest fills at next-bar-open, live fires an
  immediate market order on signal detection; expect some difference)
- Bracket order OCA behavior under real IBKR fills
- Whether IBC's forced restarts (see `AutoRestartTime` in your Gateway
  config) interrupt an open position cleanly

## Known assumptions - confirm with the client before/during the 2-week run

1. **NO-SETUP vs NO-ENTRY/score_bajo boundary** (not defined in his spec):
   implemented as leading score < 50 = NO-SETUP, 50-79.9 = NO-ENTRY/score_bajo.
2. **Blocking-reason priority order** when multiple conditions apply on one
   bar (only one `filtro_bloqueador` per row): posicion_abierta -> fuera_sesion
   -> volumen -> sin_espacio -> score_bajo -> cooldown -> NO-SETUP. Matches
   the actual structure of the validated backtest engine - see comments at
   the top of `decision_logger.py` for the full reasoning.
3. **`riesgo_usd` formula discrepancy**: his own spec example doesn't
   arithmetically match his own stated formula (`|entry-stop| x shares`).
   Implemented per the stated formula; flag to him.
4. **Logging scope**: decision rows are logged for every bar received while
   the bot runs (the data subscription's active hours), not literal 24/7.
5. **Spread/commission values** (`SPREAD_USD=0.02`, `COMMISSION_USD=1.00`
   in `config.py`) are placeholder realistic defaults, NOT sourced from an
   actual IBKR fee schedule lookup. Client asked for "real IB spread and
   commission" - confirm exact figures with him or pull from IBKR docs
   before the paper run starts.
6. **useRTH=False** carried over from the backtest data assumption - if his
   Pine reference used RTH-only data, this could still cause a small
   divergence in indicator warmup (same open question flagged during backtesting).

## Setup

### 1. Fill in Telegram credentials (`tsla_bot/config.py`)
```python
TELEGRAM_BOT_TOKEN = "..."   # from @BotFather
TELEGRAM_CHAT_ID = "..."     # from api.telegram.org/bot<TOKEN>/getUpdates
```
See the docstring at the top of `tsla_bot/telegram_bot.py` for the full
step-by-step.

### 2. Confirm IB Gateway is running and reachable
This engine expects Gateway on `127.0.0.1:4002` (matches your VPS's
confirmed-working headless IBC setup). Check `tsla_bot/config.py` if this
ever changes.

### 3. Verify no parameters have drifted from the validated baseline
`config.py` has `PAPER_RUN_LOCKED = True` and `PAPER_RUN_START_DATE` -
set the start date the day the 2-week run actually begins, and do not
edit `tsla_3factor_CORRECTED.py`'s `CONFIG` or this file's sizing values
until the run is over (per the client's explicit instruction: "if we
adjust mid-run we lose the baseline comparison").

### 4. Run the engine
```bash
cd tsla_paper_engine
python3 -m tsla_bot.engine
```
Logs go to `logs/tsla_engine.log` and stdout. Decisions log to
`logs/tsla_decisiones_master.csv` (cumulative) and
`logs/tsla_decisiones_<date>.csv` (daily).

### 5. Run the Telegram command listener (separate process)
```bash
python3 -m tsla_bot.telegram_bot
```
Handles `/export` (sends master CSV) and `/status` (today's summary so far).
The daily automatic summary (`send_daily_summary()`) needs a scheduler -
not wired to cron/systemd yet; call it from a cron job at
`config.DAILY_SUMMARY_TIME_ET` or add scheduling logic to `engine.py`.

### 6. Run the dashboard
```bash
streamlit run tsla_bot/dashboard.py
```

## File structure

```
tsla_bot/
  config.py           - IB connection, sizing, costs, logging paths, Telegram
  decision_logger.py  - 33-column CSV writer (ENTRY/NO-ENTRY/NO-SETUP)
  engine.py            - IBKR connection, live bar handling, bracket orders
  telegram_bot.py      - daily summary + /export + /status
  dashboard.py          - Streamlit dashboard for the decision-log schema
tsla_3factor_CORRECTED.py  - validated signal logic (imported by engine.py,
                              not duplicated)
```

## Next steps not covered here

- Scheduler for the daily Telegram summary (cron or in-process)
- tmux/systemd wrapper for engine.py + telegram_bot.py to survive
  SSH disconnects (same pattern as the Gold bot's tmux setup)
- Live-fire testing against a real bar stream before the 2-week run starts
