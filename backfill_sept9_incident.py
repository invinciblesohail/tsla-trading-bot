"""
ONE-TIME backfill for today's (2026-09-09) duplicate-flatten bug.

Two real signals fired today (op_id 168, 170) and were correctly logged
with their FIRST, legitimate flatten each (-$7.20 and -$8.96). But a bug
(fixed today - see engine.py comments on "emergency_flatten_triggered")
caused each incident's cancellation event to fire 4 flatten orders instead
of 1, creating a runaway short position that grew to -225 shares before
being manually corrected.

This backfills that EXTRA, unintended exposure as one row - reconciled
exactly against IBKR's full execution record for today (reqExecutions()),
not estimated. Verified: already-logged (-16.16) + this backfill (+702.30)
= grand total of all of today's real executions (+686.14).

Run ONCE: python3 backfill_sept9_incident.py
"""

import csv
import shutil
from datetime import datetime

import pandas as pd

MASTER_CSV = "logs/tsla_decisiones_master.csv"

CSV_COLUMNS = [
    "op_id", "fecha", "hora_et", "simbolo", "timeframe", "tipo_decision",
    "filtro_bloqueador", "trend_call", "trend_put", "bb_call", "bb_put",
    "space_call", "space_put", "call_score", "put_score", "direccion",
    "vol_ratio", "atr", "precio_entrada", "stop", "target", "acciones",
    "riesgo_usd", "hora_salida", "precio_salida", "motivo_salida",
    "resultado", "pnl_usd", "pnl_pct", "barras_en_posicion", "overnight",
    "modo", "observaciones",
]


def get_next_op_id():
    try:
        df = pd.read_csv(MASTER_CSV, encoding="utf-8-sig")
        if df.empty or "op_id" not in df.columns:
            return 1
        return int(df["op_id"].max()) + 1
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return 1


def blank_row():
    return {col: "" for col in CSV_COLUMNS}


trade = blank_row()
trade.update({
    "fecha": "2026-09-09",
    "hora_et": "13:50:39",   # first extra oversell of incident 1
    "simbolo": "TSLA",
    "timeframe": "5m",
    "tipo_decision": "ENTRY",
    "direccion": "PUT",
    "precio_entrada": "372.2778",
    "acciones": "225",
    "hora_salida": "15:25:06",   # the final correcting flatten
    "precio_salida": "369.1564",
    "motivo_salida": "MANUAL_FLATTEN",
    "resultado": "WIN",
    "pnl_usd": "702.30",
    "pnl_pct": "0.84",
    "overnight": "No",
    "modo": "PAPER",
    "observaciones": (
        "RETROACTIVE BACKFILL 2026-09-09: unintended short exposure "
        "caused by a duplicate-flatten bug (now fixed - see engine.py). "
        "A single bracket cancellation was reported through multiple "
        "callback events, and each one fired a full flatten order with "
        "no guard against re-firing - 4 flatten orders per incident "
        "instead of 1, across 2 real signals (op_id 168, 170) today. "
        "This row represents the EXTRA shares beyond each incident's "
        "first, legitimate flatten (already correctly logged separately "
        "at -$7.20 and -$8.96). NOT a real strategy signal - a bug "
        "artifact. Amount reconciled exactly against IBKR's full "
        "execution record for the day (grand total +$686.14, minus "
        "the -$16.16 already logged = +$702.30 here). Price/time is a "
        "weighted average across incremental fills spanning both "
        "incidents, not a single clean trade - see engine.py for the "
        "full incident writeup."
    ),
})


if __name__ == "__main__":
    backup_path = f"{MASTER_CSV}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(MASTER_CSV, backup_path)
    print(f"Backed up {MASTER_CSV} -> {backup_path}")

    trade["op_id"] = get_next_op_id()

    file_exists_with_header = True
    try:
        with open(MASTER_CSV, "r", encoding="utf-8-sig") as f:
            file_exists_with_header = bool(f.readline().strip())
    except FileNotFoundError:
        file_exists_with_header = False

    with open(MASTER_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists_with_header:
            writer.writeheader()
        writer.writerow(trade)

    print(f"Backfilled op_id {trade['op_id']}: +$702.30 (unintended exposure, now closed)")
