"""
Config for the TSLA paper-trading engine.
Strategy parameters themselves live in tsla_3factor_CORRECTED.py (CONFIG dict)
and are imported from there, NOT duplicated here - this file only holds
execution/infrastructure settings.
"""

# ---------------- IBKR connection ----------------
# Bot runs on the same VPS as IB Gateway, so localhost + the confirmed port.
IB_HOST = "127.0.0.1"
IB_PORT = 4002              # IB Gateway paper port (confirmed working)
IB_CLIENT_ID = 201           # unique - don't collide with manual test connections (99-106 already used)

# ---------------- Instrument ----------------
SYMBOL = "TSLA"
SEC_TYPE = "STK"
EXCHANGE = "SMART"
CURRENCY = "USD"

BAR_SIZE = "5 mins"
WHAT_TO_SHOW = "TRADES"     # TSLA has real volume, unlike spot gold
WARMUP_DURATION = "1 M"     # enough for EMA200 + 1H trend warmup
USE_RTH = False              # ASSUMPTION carried over from backtest - ideally re-confirm
                              # with client whether his Pine reference used RTH-only data
MARKET_DATA_TYPE = 3
POLL_INTERVAL_SECONDS = 60

# ---------------- Sizing (per client's explicit instruction) ----------------
SIZING_MODE = "risk_pct"    # NOT "percent_equity" - that was only for matching the Pine backtest
RISK_PCT = 0.01              # 1% per trade, confirmed by client for the 2-week paper run
MAX_SHARES = None            # optional safety cap

STARTING_BALANCE = 10000.0   # paper account nominal starting balance for logging/PnL% purposes

# ---------------- Costs (client asked these enabled for paper trading, per his message:
#                   "Enable real IB spread and commission") ----------------
# ASSUMPTION - these are placeholder realistic defaults, NOT sourced from an actual
# IBKR commission schedule lookup or live spread measurement. Flag to client before
# trusting PnL numbers from this phase - he may want to supply exact figures instead.
SPREAD_USD = 0.02            # per share, applied half on entry half on exit (~2 cent TSLA spread)
COMMISSION_USD = 1.00        # flat per round-turn approximation of IBKR's per-share TSLA commission
                              # (IBKR is typically ~$0.005/share, min $1 - this flat $1 approximates
                              # a small paper-trading position; revisit for larger share counts)

# ---------------- Live-only safety switches (client: leave both False for this baseline run) ----------------
CLOSE_ON_FRIDAY = False
EARNINGS_BLACKOUT = []       # e.g. ["2026-08-26", "2026-11-18"] - empty per client instruction

# ---------------- No-parameter-change safeguard ----------------
# Client: "Do not change any parameter during the two weeks - if we adjust mid-run
# we lose the baseline comparison." This is enforced by convention (don't edit
# tsla_3factor_CORRECTED.py's CONFIG or this file's sizing values while PAPER_RUN_LOCKED
# is True), not by a hard runtime lock - documented here as the source of truth.
PAPER_RUN_LOCKED = True
PAPER_RUN_START_DATE = None  # set this the day the 2-week run actually begins

# ---------------- Logging (per client's Spec_Logging_CSV_TSLA_EN spec) ----------------
LOG_DIR = "logs"
MASTER_CSV = f"{LOG_DIR}/tsla_decisiones_master.csv"
DAILY_CSV_PATTERN = f"{LOG_DIR}/tsla_decisiones_{{date}}.csv"   # {date} = YYYY-MM-DD

# ASSUMPTION (flagged to client, unconfirmed): decision rows are logged for every
# bar the bot receives from IBKR while running - i.e. the extended trading day the
# data subscription covers - not literal 24/7. Bars outside 9:30-14:00 ET within
# that window log as NO-ENTRY/fuera_sesion.

# ---------------- Telegram (new bot, per client instruction) ----------------
# Fill these in after creating the bot via @BotFather - never commit real values.
TELEGRAM_BOT_TOKEN = "Replace it with Telegram Bot Token"
TELEGRAM_CHAT_ID = "Replace it with Telegram Chat Id"
DAILY_SUMMARY_TIME_ET = (16, 5)   # 4:05 PM ET, just after the 14:00 entry session + any open trades

MODE = "PAPER"               # per spec's `modo` column - always PAPER during this phase
HEARTBEAT_FILE = f"{LOG_DIR}/heartbeat.txt"   # dashboard reads this to show live connection status
HEARTBEAT_STALE_SECONDS = 600   # if no heartbeat in this long, dashboard shows DISCONNECTED

# ---------------- Dashboard ----------------
# Lightweight password gate, NOT enterprise auth - matches the client's
# existing dashboard's login screen visually, but this is a single shared
# username/password, not per-user accounts. Change before real use.
DASHBOARD_USERNAME = "Replace it with username"
DASHBOARD_PASSWORD = "Replace it with password"

# General US market hours (NOT the strategy's narrower 9:30-14:00 entry
# session) - for the sidebar's "Market Open/Closed" indicator, matching
# the reference dashboard's broader market-status display.
# ASSUMPTION: does not account for market holidays - flags Mon-Fri
# 9:30-16:00 ET as "open" regardless of holiday calendar.
MARKET_OPEN_TIME = (9, 30)
MARKET_CLOSE_TIME = (16, 0)
