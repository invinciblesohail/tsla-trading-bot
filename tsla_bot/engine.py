"""
Live/paper trading engine for the TSLA 3-Factor system.

Reuses the EXACT validated signal logic from tsla_3factor_CORRECTED.py
(imported directly, not reimplemented) so live decisions match what was
backtested and approved by the client. This file adds:
  - IBKR connection + live bar streaming
  - Per-bar decision classification (ENTRY / NO-ENTRY+reason / NO-SETUP)
    per Spec_Logging_CSV_TSLA_EN.docx - see decision_logger.py for the
    documented assumptions on NO-SETUP boundary and blocking-reason priority
  - risk_pct position sizing (1%, per client instruction - NOT the
    percent_equity mode used only for matching the Pine backtest)
  - Bracket order execution (market entry + OCA stop/limit)
  - Trade close -> decision log update with exit/PnL detail

STATUS: built but NOT yet live-tested against a real bar stream. Same
caveat as the Gold engine: paper-test thoroughly, especially the exact
moment-of-entry price approximation (see NOTE in open_position()) and the
bracket order mechanics, before trusting this unattended.
"""

import asyncio
import logging
import sys
from datetime import timedelta

import pandas as pd
from ib_insync import IB, Contract, MarketOrder, LimitOrder, StopOrder, util

from . import config
from .decision_logger import DecisionLogger
from . import alerts

# Import the validated strategy module directly (must be on the same path)
sys.path.insert(0, ".")
import tsla_3factor_CORRECTED as strat  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(f"{config.LOG_DIR}/tsla_engine.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tsla_bot")


def make_contract() -> Contract:
    return Contract(
        secType=config.SEC_TYPE,
        symbol=config.SYMBOL,
        exchange=config.EXCHANGE,
        currency=config.CURRENCY,
    )


def position_size_risk_pct(balance, entry_price, stop_price):
    """Independent of strat.position_size() - always risk_pct here, per client instruction."""
    dist = abs(entry_price - stop_price)
    if dist <= 0:
        return 0
    shares = (balance * config.RISK_PCT) / dist
    if config.MAX_SHARES is not None:
        shares = min(shares, config.MAX_SHARES)
    return int(shares)  # whole shares only


class TslaBotEngine:
    def __init__(self):
        self.ib = IB()
        self.contract = make_contract()
        self.logger = DecisionLogger()
        self.balance = config.STARTING_BALANCE

        self.bars = None
        self.last_call_time = None
        self.last_put_time = None
        self.cooldown = timedelta(minutes=strat.CONFIG["cooldown_minutes"])

        # open_position: None or dict with side, entry_idx(time), entry_price,
        # stop, target, shares, trade_key, bars_held
        self.open_position = None
        self._pending_emergency_flatten_order_id = None

    # ---------------- connection / data ----------------

    def connect(self):
        log.info("Connecting to IBKR at %s:%s (clientId=%s)...",
                  config.IB_HOST, config.IB_PORT, config.IB_CLIENT_ID)
        self.ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)
        self.ib.reqMarketDataType(config.MARKET_DATA_TYPE)
        if config.MARKET_DATA_TYPE != 1:
            log.warning("Using non-live market data (type=%d) - see config.py "
                        "MARKET_DATA_TYPE comment.", config.MARKET_DATA_TYPE)
        self.ib.qualifyContracts(self.contract)
        log.info("Connected. Contract qualified: %s", self.contract)

    def start(self):
        if config.PAPER_RUN_LOCKED:
            log.info("PAPER_RUN_LOCKED=True: parameters must not change mid-run "
                      "(client's explicit instruction). Verify config before deploying.")
        self.connect()

        # NOTE: keepUpToDate=True historical bars were CONFIRMED (isolated
        # diagnostic test) to deliver ZERO updates under delayed market data
        # on this account, even during active market hours. Rather than rely
        # on IBKR pushing updates, we do one warmup fetch here, then POLL for
        # new closed bars on a timer (see _poll_loop). self.history_df holds
        # the full accumulated bar history that grows via polling.
        raw_bars = self.ib.reqHistoricalData(
            self.contract,
            endDateTime="",
            durationStr=config.WARMUP_DURATION,
            barSizeSetting=config.BAR_SIZE,
            whatToShow=config.WHAT_TO_SHOW,
            useRTH=config.USE_RTH,
            formatDate=2,
            keepUpToDate=False,
        )
        log.info("Historical warmup loaded: %d bars.", len(raw_bars))
        if len(raw_bars) < 250:
            msg = (f"Warmup only loaded {len(raw_bars)} bars (need 250+ for "
                   f"EMA200/indicators to be valid) - IBKR likely timed out or "
                   f"rejected the request. Engine will NOT start signal evaluation.")
            log.error(msg)
            alerts.alert_engine_error(msg)
            self.ib.disconnect()
            raise RuntimeError(msg)

        self.history_df = util.df(raw_bars)
        self.history_df["date"] = pd.to_datetime(self.history_df["date"], utc=True)
        self.history_df = self.history_df.set_index("date")
        self.last_processed_time = self.history_df.index[-1]

        self.ib.orderStatusEvent += self.on_order_status
        self.ib.disconnectedEvent += self.on_disconnected
        log.info("Engine running (polling every %ds for new bars)...", config.POLL_INTERVAL_SECONDS)

        asyncio.ensure_future(self._heartbeat_loop())
        asyncio.ensure_future(self._poll_loop())
        self.ib.run()

    async def _heartbeat_loop(self):
        # BUGFIX: previously wrote the heartbeat unconditionally, which only
        # proved the engine's asyncio loop was alive - NOT that it was
        # actually connected to IBKR. Confirmed live: after Gateway's daily
        # AutoRestartTime dropped the connection, the poll loop failed every
        # cycle with "Not connected" while the dashboard likely still showed
        # CONNECTED, since the heartbeat kept writing regardless.
        while True:
            if self.ib.isConnected():
                self._write_heartbeat()
            await asyncio.sleep(30)

    async def _poll_loop(self):
        """Re-requests recent bars on a timer and processes any that are
        newer than the last one already handled. Replaces keepUpToDate's
        push-based updates, which don't fire under delayed market data."""
        while True:
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
            try:
                if not self.ib.isConnected():
                    log.warning("Not connected to IBKR - attempting to reconnect...")
                    await self._reconnect()
                    continue  # resume normal polling on the NEXT cycle
                await self._poll_for_new_bars()
            except Exception:
                log.exception("Error while polling for new bars")
                alerts.alert_engine_error("Exception while polling for new bars - check logs/tsla_engine.log")

    async def _reconnect(self):
        """Called when the poll loop detects a dropped IBKR connection
        (e.g. Gateway's own daily AutoRestartTime, or a network blip).
        Re-establishes the connection and re-fetches a fresh warmup, since
        assuming the old self.history_df is still valid after an unknown-
        length outage is risky - restarting cleanly is safer.

        Uses connectAsync/qualifyContractsAsync, NOT the sync connect()/
        qualifyContracts() wrappers used in start() - this coroutine runs
        on the SAME event loop ib.run() already drives, and the sync
        wrappers' internal loop.run_until_complete() would hit the exact
        same 'event loop is already running' error reqHistoricalData did."""
        try:
            self.ib.disconnect()
        except Exception:
            pass
        await asyncio.sleep(5)
        try:
            await self.ib.connectAsync(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)
            self.ib.reqMarketDataType(config.MARKET_DATA_TYPE)
            await self.ib.qualifyContractsAsync(self.contract)

            raw_bars = await self.ib.reqHistoricalDataAsync(
                self.contract,
                endDateTime="",
                durationStr=config.WARMUP_DURATION,
                barSizeSetting=config.BAR_SIZE,
                whatToShow=config.WHAT_TO_SHOW,
                useRTH=config.USE_RTH,
                formatDate=2,
                keepUpToDate=False,
            )
            if len(raw_bars) < 250:
                log.error("Reconnect warmup only got %d bars - will retry next cycle.", len(raw_bars))
                return
            self.history_df = util.df(raw_bars)
            self.history_df["date"] = pd.to_datetime(self.history_df["date"], utc=True)
            self.history_df = self.history_df.set_index("date")
            self.last_processed_time = self.history_df.index[-1]
            log.info("Reconnected successfully - warmup refreshed with %d bars.", len(raw_bars))
            alerts.alert_engine_error("Reconnected to IBKR successfully after a dropped connection.")
        except Exception:
            log.exception("Reconnect attempt failed - will retry next cycle.")

    async def _poll_for_new_bars(self):
        # MUST use the Async variant here: this coroutine runs on the SAME
        # event loop that ib.run() is already driving. The synchronous
        # reqHistoricalData() wrapper internally calls
        # loop.run_until_complete(), which raises "This event loop is
        # already running" when called from inside a coroutine on that same
        # loop - confirmed by the actual traceback this produced live.
        raw_bars = await self.ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime="",
            durationStr="2 D",   # small window - just enough to catch anything new
            barSizeSetting=config.BAR_SIZE,
            whatToShow=config.WHAT_TO_SHOW,
            useRTH=config.USE_RTH,
            formatDate=2,
            keepUpToDate=False,
        )
        if not raw_bars:
            log.warning("Poll returned 0 bars.")
            return

        new_df = util.df(raw_bars)
        new_df["date"] = pd.to_datetime(new_df["date"], utc=True)
        new_df = new_df.set_index("date")

        new_rows = new_df[new_df.index > self.last_processed_time]
        if new_rows.empty:
            log.info("Poll OK - no new bars since %s.", self.last_processed_time)
            return  # nothing new yet, normal between bar closes

        # Merge into the running history (drop overlap, keep it growing)
        self.history_df = pd.concat([self.history_df, new_rows])
        self.history_df = self.history_df[~self.history_df.index.duplicated(keep="last")].sort_index()

        # The LAST row in new_rows might still be the currently-forming bar
        # (not yet closed) - only process rows up to but not including it,
        # same "don't act on the still-forming bar" principle as before.
        # BUGFIX: previously excluded only the LAST row in the batch as
        # "possibly still forming" - but this stalls forever if a poll
        # keeps returning exactly 1 new row (confirmed live: stuck 3+
        # polls in a row on the same single row, since with only 1 row
        # "closed_new_rows" was always empty and last_processed_time never
        # advanced). Correct approach: a bar is closed if its own 5-minute
        # period has actually elapsed by wall-clock time, regardless of
        # how many rows came back in this particular poll.
        bar_duration = pd.Timedelta(minutes=5)
        now_utc = pd.Timestamp.now(tz="UTC")
        closed_new_rows = new_rows[new_rows.index + bar_duration <= now_utc]

        log.info("Poll OK - found %d new row(s), %d confirmed closed: %s",
                  len(new_rows), len(closed_new_rows), list(closed_new_rows.index))

        for bar_time in closed_new_rows.index:
            self.process_closed_bar_at(bar_time)

        self.last_processed_time = closed_new_rows.index[-1] if len(closed_new_rows) else self.last_processed_time

    def process_closed_bar_at(self, bar_time):
        r = strat.generate_raw_signals(self.history_df, strat.CONFIG)
        if bar_time not in r.index:
            log.warning("Bar time %s not found in signal frame, skipping.", bar_time)
            return
        row = r.loc[bar_time]
        self.classify_and_act(bar_time, row)

    # ---------------- bar handling (order-fill callback still event-driven) ----------------

    def on_bar_update(self, bars, has_new_bar):
        # No longer used for the main data path (see _poll_loop) - kept
        # harmless in case keepUpToDate ever fires under a live subscription
        # switch; the poll loop is the authoritative path either way.
        pass

    def on_disconnected(self):
        log.warning("IBKR connection lost - heartbeat will go stale, dashboard will show DISCONNECTED shortly.")

    def _write_heartbeat(self):
        try:
            with open(config.HEARTBEAT_FILE, "w") as f:
                f.write(pd.Timestamp.now(tz="UTC").isoformat())
        except Exception:
            log.exception("Failed to write heartbeat file")

    # ---------------- decision classification (priority order - see decision_logger.py) ----------------

    def classify_and_act(self, bar_time, row):
        ny_time = bar_time.tz_convert(strat.CONFIG["session_tz"])

        scores = {
            "trend_call": row["trend_score_call"], "trend_put": row["trend_score_put"],
            "bb_call": row["bb_score_call"], "bb_put": row["bb_score_put"],
            "space_call": row["space_score_call"], "space_put": row["space_score_put"],
            "call_score": row["call_score"], "put_score": row["put_score"],
            "vol_ratio": row["volume"] / row["vol_ma"] if row["vol_ma"] > 0 else 0.0,
            "atr": row["atr"],
        }

        leading_dir = "CALL" if row["call_score"] > row["put_score"] else \
                      ("PUT" if row["put_score"] > row["call_score"] else "NO_TRADE")
        leading_score = max(row["call_score"], row["put_score"])
        threshold = strat.CONFIG["score_threshold"]

        # 1) position already open
        if self.open_position is not None:
            self.manage_open_position(bar_time, row)  # check stop/target first
            if self.open_position is not None:  # still open after the check
                self.logger.log_no_entry(ny_time, "posicion_abierta", scores, leading_dir)
                return
            # else: it just closed this bar - fall through to allow a fresh signal same bar? 
            # NO: keep it simple/conservative, one decision per bar - skip further entry logic this bar.
            return

        # 2) session filter
        if not row["in_session"]:
            self.logger.log_no_entry(ny_time, "fuera_sesion", scores, leading_dir)
            return

        # 3) volume gate (only meaningful for the leading direction)
        if not row["vol_ok"]:
            self.logger.log_no_entry(ny_time, "volumen", scores, leading_dir)
            return

        # 4) space gate for the leading direction
        no_space = row["no_space_call"] if leading_dir == "CALL" else \
                   (row["no_space_put"] if leading_dir == "PUT" else False)
        if leading_dir != "NO_TRADE" and no_space:
            self.logger.log_no_entry(ny_time, "sin_espacio", scores, leading_dir)
            return

        # 5) score threshold
        if leading_score < threshold:
            if leading_score >= 50:
                self.logger.log_no_entry(ny_time, "score_bajo", scores, leading_dir)
            else:
                self.logger.log_no_setup(ny_time, scores)
            return

        # 6) cooldown (only checked once we'd otherwise enter)
        cooldown_ok = (
            (leading_dir == "CALL" and (self.last_call_time is None or bar_time - self.last_call_time >= self.cooldown))
            or (leading_dir == "PUT" and (self.last_put_time is None or bar_time - self.last_put_time >= self.cooldown))
        )
        if not cooldown_ok:
            self.logger.log_no_entry(ny_time, "cooldown", scores, leading_dir)
            return

        # --- All gates passed: ENTRY ---
        self.open_new_position(bar_time, ny_time, row, scores, leading_dir)

    # ---------------- order management ----------------

    def open_new_position(self, bar_time, ny_time, row, scores, side):
        # ARCHITECTURE FIX (confirmed live bug, client-reported): previously
        # submitted the FULL bracket (entry + stop + target) simultaneously,
        # computing stop/target from the SIGNAL bar's approximate delayed-
        # data close. When the entry-price-correction fix later patched
        # precio_entrada to the REAL fill, stop/target were never re-anchored
        # - they stayed fixed at the pre-correction levels. Verified against
        # 7 live trades: the size of each trade's SL/TP-ratio distortion
        # correlated almost perfectly with the size of its entry-price
        # correction (e.g. trade 498: $6.63 correction -> 12.3x ATR stop
        # instead of 2.4x). This is NOT an ATR-timing bug - ATR itself was
        # read correctly, once, at the right bar. The bug was placing
        # protective orders before the real entry price was known.
        #
        # FIX: place ONLY the market entry now. Compute and submit stop/
        # target ONLY after the entry's real fill price is confirmed (see
        # on_order_status). This guarantees stop/target are ALWAYS exactly
        # sl_atr/tp_atr x ATR from the true entry, every trade, no
        # after-the-fact correction ever needed again.
        #
        # Residual risk, disclosed: there's a brief window (typically 1-2
        # seconds, based on observed live fill speed) between the entry
        # filling and the stop/target orders being submitted, during which
        # the position has no resting protective order. Far smaller than
        # the ~24h unprotected window from the earlier TIF/GTC bug, but
        # not zero - flagged transparently rather than hidden.
        close = row["close"]
        atr = row["atr"]
        if side == "CALL":
            stop = close - strat.CONFIG["sl_atr"] * atr
        else:
            stop = close + strat.CONFIG["sl_atr"] * atr

        shares = position_size_risk_pct(self.balance, close, stop)
        if shares <= 0:
            log.info("Signal fired but risk budget doesn't cover 1 share, skipping. side=%s", side)
            self.logger.log_no_entry(ny_time, "score_bajo", scores, side,
                                      observaciones="risk budget < 1 share, not a real block reason - flag to client")
            return

        action = "BUY" if side == "CALL" else "SELL"

        parent_id = self.ib.client.getReqId()
        parent = MarketOrder(action, shares)
        parent.orderId = parent_id
        parent.transmit = True
        parent.tif = "GTC"

        parent_trade = self.ib.placeOrder(self.contract, parent)

        trade_key = f"{side}_{bar_time.isoformat()}"
        # Log the ENTRY decision immediately (for audit/timing), with
        # PROVISIONAL stop/target based on the signal price - these get
        # corrected to the real, ratio-correct values the moment the fill
        # confirms (see on_order_status), same as precio_entrada already was.
        target_provisional = close + strat.CONFIG["tp_atr"] * atr if side == "CALL" \
            else close - strat.CONFIG["tp_atr"] * atr
        log_row = self.logger.log_entry(
            ny_time, scores, side, close, stop, target_provisional, shares, trade_key
        )

        self.open_position = {
            "side": side,
            "entry_time": bar_time,
            "entry_price": close,   # provisional - corrected on fill, see on_order_status
            "atr": atr,             # LOCKED at signal time - never recalculated
            "stop": stop,           # provisional until fill confirms
            "target": target_provisional,
            "shares": shares,
            "trade_key": trade_key,
            "parent_order_id": parent_id,
            "parent_trade": parent_trade,
            "stop_order_id": None,   # not yet placed - see on_order_status
            "target_order_id": None,
            "stop_trade": None,
            "target_trade": None,
            "bracket_placed": False,
            "bars_held": 0,
        }

        if side == "CALL":
            self.last_call_time = bar_time
        else:
            self.last_put_time = bar_time

        log.info("ENTRY %s shares=%d signal_price~%.2f (bracket pending real fill)",
                  side, shares, close)

    def _place_bracket_after_fill(self, pos, real_entry_price):
        """Called once the entry order's real fill is confirmed. Computes
        stop/target from the REAL entry price (never the approximate signal
        price), guaranteeing the exact configured ATR ratio every time."""
        atr = pos["atr"]
        side = pos["side"]
        shares = pos["shares"]
        if side == "CALL":
            stop = real_entry_price - strat.CONFIG["sl_atr"] * atr
            target = real_entry_price + strat.CONFIG["tp_atr"] * atr
        else:
            stop = real_entry_price + strat.CONFIG["sl_atr"] * atr
            target = real_entry_price - strat.CONFIG["tp_atr"] * atr

        reverse_action = "SELL" if side == "CALL" else "BUY"
        parent_id = pos["parent_order_id"]

        target_order = LimitOrder(reverse_action, shares, round(target, 2))
        target_order.orderId = self.ib.client.getReqId()
        target_order.parentId = parent_id
        target_order.ocaGroup = f"tsla_bracket_{parent_id}"
        target_order.ocaType = 1
        target_order.transmit = False
        target_order.tif = "GTC"

        stop_order = StopOrder(reverse_action, shares, round(stop, 2))
        stop_order.orderId = self.ib.client.getReqId()
        stop_order.parentId = parent_id
        stop_order.ocaGroup = f"tsla_bracket_{parent_id}"
        stop_order.ocaType = 1
        stop_order.transmit = True
        stop_order.tif = "GTC"

        target_trade = self.ib.placeOrder(self.contract, target_order)
        stop_trade = self.ib.placeOrder(self.contract, stop_order)

        pos["stop"] = stop
        pos["target"] = target
        pos["stop_order_id"] = stop_order.orderId
        pos["target_order_id"] = target_order.orderId
        pos["stop_trade"] = stop_trade
        pos["target_trade"] = target_trade
        pos["bracket_placed"] = True

        real_risk_usd = abs(real_entry_price - stop) * shares
        self.logger.update_entry_fill_and_bracket(
            pos["trade_key"], real_entry_price, stop, target, real_risk_usd
        )

        log.info("Bracket placed after fill: entry=%.2f stop=%.2f (%.2fx ATR) target=%.2f (%.2fx ATR)",
                  real_entry_price, stop, strat.CONFIG["sl_atr"], target, strat.CONFIG["tp_atr"])
        alerts.alert_trade_open(side, real_entry_price, stop, target, shares, real_risk_usd)

    def manage_open_position(self, bar_time, row):
        """Check whether the just-closed bar hit stop/target (belt-and-suspenders
        alongside the real IBKR bracket order fills, which drive on_order_status)."""
        if self.open_position is None:
            return
        self.open_position["bars_held"] += 1
        # Actual closing is driven by on_order_status() when IBKR reports a fill.
        # This function currently only increments bars_held; kept as a hook in
        # case a synthetic/local stop-check is needed later (e.g. if relying
        # solely on IBKR's own bracket execution proves insufficient live).

    def on_order_status(self, trade):
        if self.open_position is None:
            return
        pos = self.open_position
        order_id = trade.order.orderId

        # Finalize the emergency flatten from a bracket-cancellation event
        # (see the Cancelled-status branch below) once it actually fills.
        if order_id == self._pending_emergency_flatten_order_id and trade.orderStatus.status == "Filled":
            exit_price = trade.orderStatus.avgFillPrice
            exit_time = pd.Timestamp.now(tz="UTC")
            ny_exit_time = exit_time.tz_convert(strat.CONFIG["session_tz"])
            side = pos["side"]
            shares = pos["shares"]
            pnl_usd = (exit_price - pos["entry_price"]) * shares if side == "CALL" \
                else (pos["entry_price"] - exit_price) * shares
            pnl_pct = pnl_usd / (pos["entry_price"] * shares) * 100 if shares > 0 else 0.0
            resultado = "WIN" if pnl_usd > 0 else ("LOSS" if pnl_usd < 0 else "BE")
            self.logger.close_trade_update(
                pos["trade_key"], ny_exit_time, exit_price, "EMERGENCY_FLATTEN", resultado,
                pnl_usd, pnl_pct, pos["bars_held"],
            )
            self.balance += pnl_usd
            log.info("Emergency flatten filled at %.2f, pnl=%.2f (%.2f%%)", exit_price, pnl_usd, pnl_pct)
            alerts.alert_trade_close(side, exit_price, "EMERGENCY_FLATTEN (bracket was cancelled)", pnl_usd, pnl_pct, pos["bars_held"])
            self.open_position = None
            self._pending_emergency_flatten_order_id = None
            return

        # ENTRY order filled: NOW place stop/target using the REAL fill
        # price (see _place_bracket_after_fill) - this is the actual fix,
        # not just a log correction. Guarantees stop/target are always
        # exactly sl_atr/tp_atr x ATR from the true entry.
        if order_id == pos.get("parent_order_id") and trade.orderStatus.status == "Filled" \
                and not pos.get("bracket_placed"):
            real_entry_price = trade.orderStatus.avgFillPrice
            if real_entry_price and real_entry_price > 0:
                pos["entry_price"] = real_entry_price
                self._place_bracket_after_fill(pos, real_entry_price)
            else:
                log.error("Entry filled but avgFillPrice invalid (%s) - cannot place bracket. "
                          "Position is UNPROTECTED - manual intervention needed.", real_entry_price)
                alerts.alert_engine_error(f"Entry filled with invalid fill price ({real_entry_price}) - "
                                           f"bracket NOT placed, position unprotected. Check manually now.")
            return

        if pos["stop_order_id"] is None or order_id not in (pos["stop_order_id"], pos["target_order_id"]):
            return

        # CRITICAL SAFETY FIX: if a bracket leg gets CANCELLED (not filled)
        # while we still think a position is open, that means protection
        # was lost - exactly what happened live (both stop and target
        # expired via IBKR's DAY-TIF default at end-of-day, leaving a real
        # position naked for ~24 hours, losing -$441 with no stop firing).
        # Now fixed at the source with explicit tif="GTC" on all bracket
        # legs, but this is a second layer of defense: if a leg is EVER
        # cancelled unexpectedly for any other reason, flatten immediately
        # rather than silently leaving the position unprotected again.
        if trade.orderStatus.status == "Cancelled":
            other_leg_id = pos["target_order_id"] if order_id == pos["stop_order_id"] else pos["stop_order_id"]
            other_leg_trade = pos["target_trade"] if order_id == pos["stop_order_id"] else pos["stop_trade"]
            leg_name = "STOP" if order_id == pos["stop_order_id"] else "TARGET"
            msg = (f"{leg_name} order (id={order_id}) was CANCELLED while position is still "
                   f"open - protection lost. Flattening position immediately as a safety measure.")
            log.error(msg)
            alerts.alert_engine_error(msg)
            try:
                if other_leg_trade.orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled"):
                    self.ib.cancelOrder(other_leg_trade.order)
            except Exception:
                log.exception("Failed to cancel the other bracket leg during emergency flatten")

            side = pos["side"]
            reverse_action = "SELL" if side == "CALL" else "BUY"
            flatten_order = MarketOrder(reverse_action, pos["shares"])
            flatten_order.tif = "GTC"
            flatten_trade = self.ib.placeOrder(self.contract, flatten_order)
            log.info("Emergency flatten order submitted: %s %d shares", reverse_action, pos["shares"])
            self._pending_emergency_flatten_order_id = flatten_order.orderId
            return

        if trade.orderStatus.status != "Filled":
            return

        reason = "STOP" if order_id == pos["stop_order_id"] else "TARGET"
        exit_price = trade.orderStatus.avgFillPrice
        exit_time = pd.Timestamp.now(tz="UTC")
        ny_exit_time = exit_time.tz_convert(strat.CONFIG["session_tz"])

        side = pos["side"]
        shares = pos["shares"]
        pnl_usd = (exit_price - pos["entry_price"]) * shares if side == "CALL" \
            else (pos["entry_price"] - exit_price) * shares
        pnl_pct = pnl_usd / (pos["entry_price"] * shares) * 100 if shares > 0 else 0.0
        resultado = "WIN" if pnl_usd > 0 else ("LOSS" if pnl_usd < 0 else "BE")

        self.logger.close_trade_update(
            pos["trade_key"], ny_exit_time, exit_price, reason, resultado,
            pnl_usd, pnl_pct, pos["bars_held"],
        )
        self.balance += pnl_usd
        log.info("Position closed via %s at %.2f pnl=%.2f (%.2f%%) balance=%.2f",
                  reason, exit_price, pnl_usd, pnl_pct, self.balance)
        alerts.alert_trade_close(side, exit_price, reason, pnl_usd, pnl_pct, pos["bars_held"])
        self.open_position = None


if __name__ == "__main__":
    engine = TslaBotEngine()
    engine.start()
