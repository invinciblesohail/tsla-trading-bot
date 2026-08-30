"""
Decision logger - implements Spec_Logging_CSV_TSLA_EN.docx exactly.

Core rule from the spec: log ONE ROW PER DECISION, not just per executed
trade. NO-ENTRY (with blocking filter) and NO-SETUP decisions are logged too.

============================================================================
ASSUMPTIONS (flagged - not fully specified in the client's doc, confirm with him)
============================================================================
1. NO-SETUP vs NO-ENTRY/score_bajo boundary: the spec doesn't define exactly
   where "nothing happening" ends and "a real but insufficient signal" begins.
   Implemented here: NO-SETUP = leading score < 50 (quiet bar).
   NO-ENTRY/score_bajo = leading score in [50, threshold) - a real near-miss.

2. Priority order when multiple blocking conditions apply on the same bar
   (only one filtro_bloqueador value can be logged per row). Order chosen to
   match the ACTUAL structure of the validated backtest engine
   (tsla_3factor_CORRECTED.py run_backtest()):
     posicion_abierta -> fuera_sesion -> volumen -> sin_espacio
     -> score_bajo -> cooldown -> (else) NO-SETUP
   posicion_abierta is checked first because the backtest engine literally
   gates signal evaluation on "if position is None and pending is None"
   BEFORE looking at raw_call/raw_put at all. fuera_sesion/volumen/
   sin_espacio/score_bajo follow the exact left-to-right AND order inside
   raw_call/raw_put's definition. cooldown is checked last because in the
   backtest it's only evaluated once raw_call/raw_put are already True.

3. Decision rows are logged for every bar received while the bot is running
   (the data subscription's active hours), not literal 24/7 - see config.py.
============================================================================
"""

import csv
import os
from datetime import datetime

from . import config

CSV_COLUMNS = [
    "op_id", "fecha", "hora_et", "simbolo", "timeframe", "tipo_decision",
    "filtro_bloqueador", "trend_call", "trend_put", "bb_call", "bb_put",
    "space_call", "space_put", "call_score", "put_score", "direccion",
    "vol_ratio", "atr", "precio_entrada", "stop", "target", "acciones",
    "riesgo_usd", "hora_salida", "precio_salida", "motivo_salida",
    "resultado", "pnl_usd", "pnl_pct", "barras_en_posicion", "overnight",
    "modo", "observaciones",
]


def _fmt_num(x, decimals):
    if x is None:
        return ""
    return f"{x:.{decimals}f}"


def _fmt_price(x):
    return _fmt_num(x, 2)


def _fmt_score(x):
    return _fmt_num(x, 1)


class DecisionLogger:
    def __init__(self):
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self.op_id = self._recover_last_op_id() + 1
        self._ensure_header(config.MASTER_CSV)
        self._open_trade_rows = {}  # keyed by a trade identifier -> row dict, for later update on exit

    def _recover_last_op_id(self):
        if not os.path.exists(config.MASTER_CSV):
            return 0
        last_id = 0
        with open(config.MASTER_CSV, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    last_id = max(last_id, int(row["op_id"]))
                except (ValueError, KeyError):
                    pass
        return last_id

    def _ensure_header(self, path):
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()

    def _daily_csv_path(self, date_str):
        return config.DAILY_CSV_PATTERN.format(date=date_str)

    def _append_row(self, row: dict):
        date_str = row["fecha"]
        daily_path = self._daily_csv_path(date_str)
        self._ensure_header(daily_path)
        for path in (config.MASTER_CSV, daily_path):
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writerow(row)

    def _base_row(self, bar_time_et, tipo_decision, filtro_bloqueador,
                   trend_call, trend_put, bb_call, bb_put,
                   space_call, space_put, call_score, put_score,
                   direccion, vol_ratio, atr, observaciones=""):
        row = {
            "op_id": self.op_id,
            "fecha": bar_time_et.strftime("%Y-%m-%d"),
            "hora_et": bar_time_et.strftime("%H:%M:%S"),
            "simbolo": config.SYMBOL,
            "timeframe": "5m",
            "tipo_decision": tipo_decision,
            "filtro_bloqueador": filtro_bloqueador or "",
            "trend_call": _fmt_score(trend_call),
            "trend_put": _fmt_score(trend_put),
            "bb_call": _fmt_score(bb_call),
            "bb_put": _fmt_score(bb_put),
            "space_call": _fmt_score(space_call),
            "space_put": _fmt_score(space_put),
            "call_score": _fmt_score(call_score),
            "put_score": _fmt_score(put_score),
            "direccion": direccion,
            "vol_ratio": _fmt_num(vol_ratio, 2),
            "atr": _fmt_num(atr, 2),
            "precio_entrada": "",
            "stop": "",
            "target": "",
            "acciones": "",
            "riesgo_usd": "",
            "hora_salida": "",
            "precio_salida": "",
            "motivo_salida": "",
            "resultado": "",
            "pnl_usd": "",
            "pnl_pct": "",
            "barras_en_posicion": "",
            "overnight": "",
            "modo": config.MODE,
            "observaciones": observaciones,
        }
        self.op_id += 1
        return row

    def log_no_setup(self, bar_time_et, scores, observaciones=""):
        row = self._base_row(
            bar_time_et, "NO-SETUP", None,
            scores["trend_call"], scores["trend_put"],
            scores["bb_call"], scores["bb_put"],
            scores["space_call"], scores["space_put"],
            scores["call_score"], scores["put_score"],
            "NO_TRADE", scores["vol_ratio"], scores["atr"],
            observaciones,
        )
        self._append_row(row)
        return row

    def log_no_entry(self, bar_time_et, filtro_bloqueador, scores, direccion,
                      observaciones=""):
        row = self._base_row(
            bar_time_et, "NO-ENTRY", filtro_bloqueador,
            scores["trend_call"], scores["trend_put"],
            scores["bb_call"], scores["bb_put"],
            scores["space_call"], scores["space_put"],
            scores["call_score"], scores["put_score"],
            direccion, scores["vol_ratio"], scores["atr"],
            observaciones,
        )
        self._append_row(row)
        return row

    def log_entry(self, bar_time_et, scores, direccion, entry_price, stop,
                   target, shares, trade_key, observaciones=""):
        """Logs the ENTRY row and keeps it open (in-memory) for later exit update."""
        row = self._base_row(
            bar_time_et, "ENTRY", None,
            scores["trend_call"], scores["trend_put"],
            scores["bb_call"], scores["bb_put"],
            scores["space_call"], scores["space_put"],
            scores["call_score"], scores["put_score"],
            direccion, scores["vol_ratio"], scores["atr"],
            observaciones,
        )
        risk_usd = abs(entry_price - stop) * shares
        row["precio_entrada"] = _fmt_price(entry_price)
        row["stop"] = _fmt_price(stop)
        row["target"] = _fmt_price(target)
        row["acciones"] = str(int(shares))
        row["riesgo_usd"] = _fmt_price(risk_usd)

        self._append_row(row)
        # Keep this row (and its file position context) so we can emit a
        # corresponding update when the trade closes. Since CSV doesn't
        # support in-place row edits easily, the exit gets logged as an
        # UPDATE by rewriting - see close_trade_update() below.
        row["_entry_date"] = bar_time_et.date()
        self._open_trade_rows[trade_key] = row
        return row

    def update_entry_fill(self, trade_key, real_entry_price, real_risk_usd):
        """
        Corrects precio_entrada/riesgo_usd once the ENTRY order's actual fill
        price is known (see engine.py on_order_status). Necessary because the
        row is initially logged using the signal bar's delayed-data close as
        an approximation, before the real market order has actually filled -
        confirmed live to diverge meaningfully (17x PnL discrepancy on the
        first real trade) since delayed data can be 15-20 min stale.
        """
        entry_row = self._open_trade_rows.get(trade_key)
        if entry_row is None:
            return  # trade already closed or unknown - nothing to correct

        entry_row["precio_entrada"] = _fmt_price(real_entry_price)
        entry_row["riesgo_usd"] = _fmt_price(real_risk_usd)

        patch = {
            "precio_entrada": _fmt_price(real_entry_price),
            "riesgo_usd": _fmt_price(real_risk_usd),
        }
        op_id = entry_row["op_id"]
        entry_date_str = entry_row["fecha"]
        daily_path = self._daily_csv_path(entry_date_str)
        for path in (config.MASTER_CSV, daily_path):
            self._patch_row_by_op_id(path, op_id, patch)

    def close_trade_update(self, trade_key, exit_time_et, exit_price,
                            motivo_salida, resultado, pnl_usd, pnl_pct,
                            barras_en_posicion):
        """
        Rewrites the ENTRY row (in both master and that day's daily CSV) with
        exit details filled in. CSV files don't support in-place edits, so
        this reads, patches the matching op_id row, and rewrites the file.
        Called once, when the trade actually closes.
        """
        entry_row = self._open_trade_rows.pop(trade_key, None)
        if entry_row is None:
            return  # nothing to update - shouldn't happen, but don't crash the engine over it

        overnight = "Si" if exit_time_et.date() != entry_row["_entry_date"] else "No"

        patch = {
            "hora_salida": exit_time_et.strftime("%H:%M:%S"),
            "precio_salida": _fmt_price(exit_price),
            "motivo_salida": motivo_salida,
            "resultado": resultado,
            "pnl_usd": _fmt_price(pnl_usd),
            "pnl_pct": _fmt_num(pnl_pct, 2),
            "barras_en_posicion": str(barras_en_posicion),
            "overnight": overnight,
        }

        op_id = entry_row["op_id"]
        entry_date_str = entry_row["fecha"]
        daily_path = self._daily_csv_path(entry_date_str)

        for path in (config.MASTER_CSV, daily_path):
            self._patch_row_by_op_id(path, op_id, patch)

    @staticmethod
    def _patch_row_by_op_id(path, op_id, patch: dict):
        if not os.path.exists(path):
            return
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames

        for row in rows:
            if str(row.get("op_id")) == str(op_id):
                row.update(patch)
                break

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
