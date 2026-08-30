"""
============================================================================
SISTEMA 3 FACTORES - TSLA - CORRECTED VERSION
Tendencia(15%) . Bollinger(50%) . Espacio Operativo(35%) + Volume gate
============================================================================

CONFIG:  TF 5m | SL 2.4 ATR | TP 3.0 ATR | Cooldown 10 min | Threshold 80
         Volume gate: current volume >= 1.5x the 20-bar volume average

PINE REFERENCE (2 Feb - 7 Aug 2026, TSLA NASDAQ, 5m):
    130 trades | 39.23% WR | PF 1.374 (dollars) | +21.55% | DD 8.14%
    -> Normalized PF (per-trade %, no compounding): 1.196
    -> The normalized figure is the real edge. Match trade count first.

WHAT CHANGED vs the original Gold file (same 6 fixes, all marked "# FIX"):
    FIX 1 - VWAP now resets daily (Pine's ta.vwap resets; cumsum() did not)
    FIX 2 - stdev uses ddof=0 (Pine population stdev, not pandas sample stdev)
    FIX 3 - prev-day high/low grouped by session day, not UTC midnight
    FIX 4 - HTF 1H trend: removed LOOKAHEAD BIAS (was reading future data)
    FIX 5 - entry executes at NEXT bar open (Pine has no process_orders_on_close)
    FIX 6 - cooldown timer only resets on an ACTUAL entry, not on a raw signal

NEW vs the Gold file:
    - Volume gate (vol_min_mult). Gold did not use one; TSLA requires 1.5x.
    - Optional Friday-close and earnings-blackout for live gap protection.
      Both default to False so the backtest matches Pine exactly.

Requires: pandas, numpy
Input: DataFrame with columns open, high, low, close, volume; datetime index with tz.
============================================================================
"""

import pandas as pd
import numpy as np
from datetime import timedelta


# ============================================================================
# CONFIGURATION - TSLA
# ============================================================================
CONFIG = {
    "ema_fast": 20,
    "ema_mid": 40,
    "ema_major": 100,
    "ema_heavy": 200,
    "htf": "1h",
    "slope_bars": 8,
    "bb_len": 20,
    "bb_mult": 2.0,
    "bb_slope_bars": 3,
    "atr_len": 14,
    "min_space_atr": 0.8,
    "good_space_atr": 3.0,
    "score_threshold": 80,          # TSLA uses 80 (Gold used 75)
    "w_trend": 15,
    "w_bb": 50,
    "w_space": 35,
    "sl_atr": 2.4,                  # TSLA
    "tp_atr": 3.0,                  # TSLA
    "cooldown_minutes": 10,         # TSLA uses 10 (Gold used 15)
    "vol_ma_len": 20,               # NEW - volume gate
    "vol_min_mult": 1.5,            # NEW - 0 disables the gate
    "session_start": (9, 30),
    "session_end": (14, 0),
    "skip_first_bar": True,
    "skip_last_bar": True,
    "session_tz": "America/New_York",
    # --- Live gap protection. Keep False for the backtest comparison. ---
    "close_on_friday": False,
    "friday_close_time": (15, 45),  # ET
    "earnings_blackout": [],        # e.g. ["2026-08-26", "2026-11-18"]
}

# --- Backtest parameters ---
STARTING_BALANCE = 10000.0

# "percent_equity" replicates the Pine strategy() settings (95% of equity)
# "risk_pct" is what the live IB bot should use
SIZING_MODE = "percent_equity"
EQUITY_PCT  = 0.95
RISK_PCT    = 0.01                  # 1% for the paper trading phase
MAX_SHARES  = None

# --- Execution costs. 0 for the first apples-to-apples run vs Pine. ---
SPREAD_USD     = 0.0                # per share, applied on entry and exit
COMMISSION_USD = 0.0                # flat per round turn

DATA_PATH = "./data/tsla_5m.csv"
BT_START  = "2026-02-02"
BT_END    = "2026-08-07 23:59:59"


# ============================================================================
# BASE INDICATORS
# ============================================================================
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def atr(df, length):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder's RMA - matches Pine's ta.atr()
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def vwap(df, tz):
    """
    FIX 1 - Pine's ta.vwap() RESETS every session/day.
    A plain cumsum() over the whole dataset drifts far from price and stops
    acting as an obstacle inside Espacio Operativo.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    idx = df.index.tz_convert(tz) if df.index.tz is not None else df.index
    day = pd.Series(idx.normalize(), index=df.index)
    pv = (typical * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return pv / vv


def bollinger(close, length, mult):
    """
    FIX 2 - Pine's ta.stdev() uses POPULATION stdev (ddof=0).
    pandas .std() defaults to SAMPLE (ddof=1) -> bands ~2.6% too wide.
    """
    basis = ema(close, length)
    dev = mult * close.rolling(length).std(ddof=0)
    return basis, basis + dev, basis - dev


def compute_indicators(df, cfg):
    df = df.copy()
    df["ema20"]  = ema(df["close"], cfg["ema_fast"])
    df["ema40"]  = ema(df["close"], cfg["ema_mid"])
    df["ema100"] = ema(df["close"], cfg["ema_major"])
    df["ema200"] = ema(df["close"], cfg["ema_heavy"])
    df["atr"]    = atr(df, cfg["atr_len"])
    df["vwap"]   = vwap(df, cfg["session_tz"])

    basis, bb_u, bb_l = bollinger(df["close"], cfg["bb_len"], cfg["bb_mult"])
    df["bb_basis"] = basis
    df["bb_upper"] = bb_u
    df["bb_lower"] = bb_l
    df["bb_slope"] = basis - basis.shift(cfg["bb_slope_bars"])

    # NEW - volume gate (Pine: volume >= volMinMult * ta.sma(volume, volMaLen))
    df["vol_ma"] = df["volume"].rolling(cfg["vol_ma_len"]).mean()
    if cfg["vol_min_mult"] and cfg["vol_min_mult"] > 0:
        df["vol_ok"] = df["volume"] >= cfg["vol_min_mult"] * df["vol_ma"]
    else:
        df["vol_ok"] = True

    # FIX 3 - previous day high/low by SESSION day (broker tz), not UTC midnight
    idx = df.index.tz_convert(cfg["session_tz"]) if df.index.tz is not None else df.index
    day = pd.Series(idx.normalize(), index=df.index)
    daily_high = df["high"].groupby(day).max().shift(1)
    daily_low  = df["low"].groupby(day).min().shift(1)
    df["pd_high"] = day.map(daily_high)
    df["pd_low"]  = day.map(daily_low)

    return df


# ============================================================================
# 1. TREND (1H + current TF)
# ============================================================================
def trend_scores(df, cfg):
    """
    FIX 4 - LOOKAHEAD BIAS REMOVED. The most damaging bug in the original.

    Original line:
        df["close"].resample("1h").last().ffill().reindex(df.index, method="ffill")

    resample("1h") labels each bucket with the hour START, so the bucket
    labelled 13:00 holds the 13:55 close. A 5-minute bar at 13:05 was then
    reading the 13:55 close - FUTURE DATA.

    Pine uses lookahead=barmerge.lookahead_off, which returns the last
    ALREADY CLOSED 1H bar. label="right", closed="left" reproduces that.
    """
    htf_close = df["close"].resample(cfg["htf"], label="right", closed="left").last().ffill()

    htf_e20 = ema(htf_close, cfg["ema_fast"])
    htf_e40 = ema(htf_close, cfg["ema_mid"])
    htf_e20_ago = htf_e20.shift(cfg["slope_bars"])

    htf_e20     = htf_e20.reindex(df.index, method="ffill")
    htf_e40     = htf_e40.reindex(df.index, method="ffill")
    htf_e20_ago = htf_e20_ago.reindex(df.index, method="ffill")

    htf_bullish = (htf_e20 > htf_e40) & (htf_e20 > htf_e20_ago)
    htf_bearish = (htf_e20 < htf_e40) & (htf_e20 < htf_e20_ago)

    ema20_ago = df["ema20"].shift(cfg["slope_bars"])
    ltf_bullish = (df["ema20"] > df["ema40"]) & (df["ema20"] > ema20_ago)
    ltf_bearish = (df["ema20"] < df["ema40"]) & (df["ema20"] < ema20_ago)

    df["trend_score_call"] = np.where(htf_bullish & ltf_bullish, 100.0,
                             np.where(htf_bullish | ltf_bullish, 50.0, 0.0))
    df["trend_score_put"]  = np.where(htf_bearish & ltf_bearish, 100.0,
                             np.where(htf_bearish | ltf_bearish, 50.0, 0.0))
    return df


# ============================================================================
# 2. ESPACIO OPERATIVO
# ============================================================================
def _between(x, a, b):
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return (x > lo) & (x < hi)


def space_scores(df, cfg):
    close = df["close"]
    e20, e40, e100, e200 = df["ema20"], df["ema40"], df["ema100"], df["ema200"]

    pair1 = ~(_between(e100, e20, e40) | _between(e200, e20, e40)) & (e40 > e20)
    pair2 = ~(_between(e20, e40, e100) | _between(e200, e40, e100)) & (e100 > e40)
    pair3 = ~(_between(e20, e100, e200) | _between(e40, e100, e200)) & (e200 > e100)

    base = df[["bb_upper", "bb_lower", "vwap", "pd_high", "pd_low"]].to_numpy(float)
    emas = {k: df[k].to_numpy(float) for k in ["ema20", "ema40", "ema100", "ema200"]}
    close_np = close.to_numpy(float)
    atr_np = df["atr"].to_numpy(float)
    p1, p2, p3 = pair1.to_numpy(), pair2.to_numpy(), pair3.to_numpy()

    nearest_above = np.full(len(df), np.nan)
    nearest_below = np.full(len(df), np.nan)

    for i in range(len(df)):
        cand = list(base[i])
        if p1[i]:
            cand += [emas["ema20"][i], emas["ema40"][i]]
        if p2[i]:
            cand += [emas["ema40"][i], emas["ema100"][i]]
        if p3[i]:
            cand += [emas["ema100"][i], emas["ema200"][i]]

        c = close_np[i]
        above = [v for v in cand if not np.isnan(v) and v > c]
        below = [v for v in cand if not np.isnan(v) and v < c]
        if above:
            nearest_above[i] = min(above)
        if below:
            nearest_below[i] = max(below)

    good, min_ = cfg["good_space_atr"], cfg["min_space_atr"]
    space_above = np.where(np.isnan(nearest_above), good, (nearest_above - close_np) / atr_np)
    space_below = np.where(np.isnan(nearest_below), good, (close_np - nearest_below) / atr_np)

    df["space_score_call"] = np.clip((space_above - min_) / (good - min_) * 100, 0, 100)
    df["space_score_put"]  = np.clip((space_below - min_) / (good - min_) * 100, 0, 100)
    df["no_space_call"] = space_above < min_
    df["no_space_put"]  = space_below < min_
    return df


# ============================================================================
# 3. BOLLINGER
# ============================================================================
def bb_scores(df):
    upper_opening = df["bb_upper"] > df["bb_upper"].shift(1)
    lower_opening = df["bb_lower"] < df["bb_lower"].shift(1)
    only_upper = upper_opening & ~lower_opening
    only_lower = lower_opening & ~upper_opening
    both_open  = upper_opening & lower_opening
    slope = df["bb_slope"]

    df["bb_score_call"] = np.select(
        [only_upper, only_lower, both_open & (slope > 0), both_open & (slope < 0)],
        [100.0, 0.0, 100.0, 0.0], default=50.0)
    df["bb_score_put"] = np.select(
        [only_lower, only_upper, both_open & (slope < 0), both_open & (slope > 0)],
        [100.0, 0.0, 100.0, 0.0], default=50.0)
    return df


# ============================================================================
# SESSION FILTER
# ============================================================================
def in_session(idx, cfg):
    ny = idx.tz_convert(cfg["session_tz"]) if idx.tz is not None \
        else idx.tz_localize("UTC").tz_convert(cfg["session_tz"])
    minutes = ny.hour * 60 + ny.minute
    start = cfg["session_start"][0] * 60 + cfg["session_start"][1]
    end   = cfg["session_end"][0] * 60 + cfg["session_end"][1]
    tf = int((idx[1] - idx[0]).total_seconds() / 60) if len(idx) > 1 else 5

    window = (minutes >= start) & (minutes < end)
    skip = np.zeros(len(idx), dtype=bool)
    if cfg["skip_first_bar"]:
        skip |= (minutes == start)
    if cfg["skip_last_bar"]:
        skip |= (minutes == end - tf)

    ok = window & ~skip

    # Optional earnings blackout (live protection; empty by default)
    if cfg.get("earnings_blackout"):
        dates = pd.to_datetime(cfg["earnings_blackout"]).date
        ok &= ~np.isin(ny.date, dates)

    return pd.Series(ok, index=idx)


# ============================================================================
# RAW SIGNALS  (cooldown applied later - see FIX 6)
# ============================================================================
def generate_raw_signals(df, cfg):
    df = compute_indicators(df, cfg)
    df = trend_scores(df, cfg)
    df = space_scores(df, cfg)
    df = bb_scores(df)

    total_w = cfg["w_trend"] + cfg["w_bb"] + cfg["w_space"]
    df["call_score"] = (df["trend_score_call"] * cfg["w_trend"] +
                        df["bb_score_call"] * cfg["w_bb"] +
                        df["space_score_call"] * cfg["w_space"]) / total_w
    df["put_score"]  = (df["trend_score_put"] * cfg["w_trend"] +
                        df["bb_score_put"] * cfg["w_bb"] +
                        df["space_score_put"] * cfg["w_space"]) / total_w

    df["in_session"] = in_session(df.index, cfg)
    threshold = cfg["score_threshold"]

    df["raw_call"] = (df["in_session"] & df["vol_ok"] & ~df["no_space_call"] &
                      (df["call_score"] >= threshold) &
                      (df["call_score"] > df["put_score"]))
    df["raw_put"]  = (df["in_session"] & df["vol_ok"] & ~df["no_space_put"] &
                      (df["put_score"] >= threshold) &
                      (df["put_score"] > df["call_score"]))

    df["sl_call"] = df["close"] - cfg["sl_atr"] * df["atr"]
    df["tp_call"] = df["close"] + cfg["tp_atr"] * df["atr"]
    df["sl_put"]  = df["close"] + cfg["sl_atr"] * df["atr"]
    df["tp_put"]  = df["close"] - cfg["tp_atr"] * df["atr"]
    return df


# ============================================================================
# POSITION SIZING
# ============================================================================
def position_size(balance, entry_price, stop_price):
    if SIZING_MODE == "percent_equity":
        if entry_price <= 0:
            return 0.0
        shares = (balance * EQUITY_PCT) / entry_price
    else:
        dist = abs(entry_price - stop_price)
        if dist <= 0:
            return 0.0
        shares = (balance * RISK_PCT) / dist

    if MAX_SHARES is not None:
        shares = min(shares, MAX_SHARES)
    return max(shares, 0.0)


# ============================================================================
# BACKTEST ENGINE
# ============================================================================
def run_backtest(df, cfg):
    r = generate_raw_signals(df, cfg)
    idx = r.index
    n = len(r)

    ny = idx.tz_convert(cfg["session_tz"]) if idx.tz is not None else idx
    is_friday = (ny.dayofweek == 4)
    fri_minutes = cfg["friday_close_time"][0] * 60 + cfg["friday_close_time"][1]
    bar_minutes = ny.hour * 60 + ny.minute

    op = r["open"].to_numpy(float)
    hi = r["high"].to_numpy(float)
    lo = r["low"].to_numpy(float)
    cl = r["close"].to_numpy(float)
    raw_call = r["raw_call"].to_numpy(bool)
    raw_put  = r["raw_put"].to_numpy(bool)
    sl_c, tp_c = r["sl_call"].to_numpy(float), r["tp_call"].to_numpy(float)
    sl_p, tp_p = r["sl_put"].to_numpy(float),  r["tp_put"].to_numpy(float)

    balance = STARTING_BALANCE
    position = None
    pending = None
    last_call_time = None
    last_put_time = None
    cooldown = timedelta(minutes=cfg["cooldown_minutes"])

    trades = []
    equity_curve = []

    def close_trade(i, raw_price, reason):
        nonlocal balance, position
        side = position["side"]
        sh = position["shares"]
        exit_price = raw_price - SPREAD_USD / 2 if side == "CALL" else raw_price + SPREAD_USD / 2
        pnl = (exit_price - position["entry_price"]) * sh if side == "CALL" \
            else (position["entry_price"] - exit_price) * sh
        pnl -= COMMISSION_USD

        trades.append({
            "side": side,
            "entry_time": idx[position["entry_idx"]],
            "entry_price": position["entry_price"],
            "stop": position["stop"],
            "target": position["target"],
            "shares": round(sh, 4),
            "exit_time": idx[i],
            "exit_price": exit_price,
            "exit_reason": reason,
            "bars_held": i - position["entry_idx"],
            "balance_before": balance,
            "balance_after": balance + pnl,
            "pnl_dollars": pnl,
            "pnl_pct": pnl / (position["entry_price"] * sh) * 100 if sh > 0 else 0.0,
        })
        balance += pnl
        position = None

    for i in range(n):

        # --- 1) FIX 5: fill a pending entry at THIS bar's OPEN ---
        if position is None and pending is not None:
            raw_entry = op[i]
            if not np.isnan(raw_entry):
                entry = raw_entry + SPREAD_USD / 2 if pending["side"] == "CALL" \
                    else raw_entry - SPREAD_USD / 2
                sh = position_size(balance, entry, pending["stop"])
                if sh > 0:
                    position = {
                        "side": pending["side"],
                        "entry_idx": i,
                        "entry_price": entry,
                        "stop": pending["stop"],
                        "target": pending["target"],
                        "shares": sh,
                    }
            pending = None

        # --- 2) manage the open position (including its entry bar) ---
        if position is not None:
            stop, target = position["stop"], position["target"]
            if position["side"] == "CALL":
                hit_stop = lo[i] <= stop
                hit_target = hi[i] >= target
            else:
                hit_stop = hi[i] >= stop
                hit_target = lo[i] <= target

            if hit_stop and hit_target:
                close_trade(i, stop, "STOP (both hit, conservative)")
            elif hit_stop:
                close_trade(i, stop, "STOP")
            elif hit_target:
                close_trade(i, target, "TARGET")
            elif cfg["close_on_friday"] and is_friday[i] and bar_minutes[i] >= fri_minutes:
                close_trade(i, cl[i], "FRIDAY CLOSE")

        # --- 3) FIX 6: cooldown resets ONLY on an actual entry ---
        if position is None and pending is None:
            ts = idx[i]
            if raw_call[i] and (last_call_time is None or ts - last_call_time >= cooldown):
                pending = {"side": "CALL", "stop": sl_c[i], "target": tp_c[i]}
                last_call_time = ts
            elif raw_put[i] and (last_put_time is None or ts - last_put_time >= cooldown):
                pending = {"side": "PUT", "stop": sl_p[i], "target": tp_p[i]}
                last_put_time = ts

        equity_curve.append(balance)

    return pd.DataFrame(trades), balance, pd.Series(equity_curve, index=idx)


# ============================================================================
# SUMMARY  - reports BOTH dollar PF and normalized PF
# ============================================================================
def summarize(trades, final_balance, equity):
    if trades.empty:
        print("No trades generated.")
        return

    wins = trades[trades.pnl_dollars > 0]
    losses = trades[trades.pnl_dollars < 0]
    pf_usd = wins.pnl_dollars.sum() / abs(losses.pnl_dollars.sum()) if len(losses) else float("inf")

    # Normalized: per-trade percentage return, removes the compounding effect
    wp = trades[trades.pnl_pct > 0].pnl_pct
    lp = trades[trades.pnl_pct < 0].pnl_pct
    pf_norm = wp.sum() / abs(lp.sum()) if len(lp) else float("inf")
    ratio = wp.mean() / abs(lp.mean()) if len(lp) else float("inf")
    breakeven = 100 / (1 + ratio)
    wr = len(wins) / len(trades) * 100

    dd = ((equity - equity.cummax()) / equity.cummax()).min() * 100
    duration = (trades.exit_time - trades.entry_time).dt.total_seconds() / 3600
    overnight = (trades.entry_time.dt.date != trades.exit_time.dt.date).sum()

    print("SISTEMA 3 FACTORES - TSLA - BACKTEST RESULTS (CORRECTED)")
    print("=" * 64)
    print(f"Period:            {trades.entry_time.min()}  ->  {trades.entry_time.max()}")
    print(f"Sizing mode:       {SIZING_MODE}")
    print(f"Spread / Comm:     {SPREAD_USD} / {COMMISSION_USD}")
    print("-" * 64)
    print(f"Total Trades:      {len(trades)}   ({len(wins)}W / {len(losses)}L)")
    print(f"Win Rate:          {wr:.2f}%")
    print(f"Final Balance:     ${final_balance:,.2f}")
    print(f"Net Profit:        ${final_balance - STARTING_BALANCE:,.2f} "
          f"({(final_balance / STARTING_BALANCE - 1) * 100:+.2f}%)")
    print(f"Profit Factor $:   {pf_usd:.3f}   <- inflated by compounding")
    print(f"Profit Factor %:   {pf_norm:.3f}   <- THE REAL EDGE")
    print(f"Avg win / avg loss:{ratio:.3f}")
    print(f"Breakeven WR:      {breakeven:.2f}%   |   Margin: {wr - breakeven:+.2f} pts")
    print(f"Max Drawdown:      {dd:.2f}%")
    print(f"Avg duration:      {duration.mean():.2f} h   |   Max: {duration.max():.2f} h")
    print(f"Overnight trades:  {overnight} of {len(trades)}")
    print("=" * 64)
    print("PINE TARGET (2 Feb - 7 Aug 2026):")
    print("   130 trades | 39.23% WR | PF$ 1.374 | PF% 1.196 | +21.55% | DD 8.14%")
    print("=" * 64)
    print("\nBy exit reason:")
    print(trades.groupby("exit_reason")["pnl_dollars"].agg(["count", "sum", "mean"]))
    print("\nBy direction:")
    print(trades.groupby("side")["pnl_dollars"].agg(["count", "sum", "mean"]))


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    df = pd.read_csv(DATA_PATH)
    # adapt this block to your CSV's timestamp column name
    ts_col = "date" if "date" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.sort_values(ts_col).set_index(ts_col)
    df.columns = [c.lower() for c in df.columns]
    df = df.loc[BT_START:BT_END].sort_index()

    trades, final_balance, equity = run_backtest(df, CONFIG)
    summarize(trades, final_balance, equity)

    trades.to_csv("tsla_backtest_trades.csv", index=False)
    print("\nTrade list exported to tsla_backtest_trades.csv")
