"""
ONE-TIME correction script for two known-bad rows in the decision log,
both predating fixes we made mid-run:

  op_id 120 (2026-08-27 09:40 ET, first-ever trade):
    - precio_entrada was never corrected to the real fill (349.02 approx
      -> 350.64 real) because the entry-fill-correction fix didn't exist
      yet at the time.
    - pnl_usd was $124.96 (calculated from the approximate entry) instead
      of IBKR's actual realizedPNL of $7.41.

  op_id 158 (2026-08-27 12:55 ET, second trade):
    - Never closed in the CSV at all. This position's bracket orders both
      expired via the TIF/DAY bug (see README "Known Issues #2") leaving
      it unprotected for ~24 hours. It was manually flattened via a
      separate diagnostic script on 2026-08-28, which bypassed the
      engine's normal close-tracking - so the CSV still shows it as open.
    - Real outcome, confirmed via IBKR's own realizedPNL: -$443.08.

Run this ONCE on the VPS, against the real master CSV and the 2026-08-27
daily CSV. Back up both files first (the script also does this itself).

Usage: python3 correct_historical_trades.py
"""

import csv
import shutil
from datetime import datetime

FILES_TO_PATCH = [
    "logs/tsla_decisiones_master.csv",
    "logs/tsla_decisiones_2026-08-27.csv",
]

# ---- Correction for op_id 120 ----
PATCH_120 = {
    "precio_entrada": "350.64",
    "stop": "347.62",       # unchanged, listed for completeness/verification
    "riesgo_usd": "214.42",
    "pnl_usd": "7.41",
    "pnl_pct": "0.03",
    "observaciones": "CORRECTED 2026-09-01: entry price and PnL updated to "
                      "real IBKR fill (was approx entry 349.02 / pnl 124.96, "
                      "based on delayed-data signal price before the "
                      "entry-fill-correction fix existed).",
}

# ---- Correction for op_id 158 ----
PATCH_158 = {
    "hora_salida": "14:22:00",
    "precio_salida": "346.73",
    "motivo_salida": "MANUAL_FLATTEN",
    "resultado": "LOSS",
    "pnl_usd": "-443.08",
    "pnl_pct": "-2.27",
    "barras_en_posicion": "305",  # approximate - spans an overnight gap
    "overnight": "Si",
    "observaciones": "CORRECTED 2026-09-01: this position's bracket orders "
                      "(both stop and target) expired due to IBKR's TIF=DAY "
                      "default (see README Known Issue #2), leaving it "
                      "unprotected for ~24h. Manually flattened via a "
                      "separate script on 2026-08-28 - this row was never "
                      "closed in the CSV until this correction. Real loss "
                      "confirmed via IBKR's own realizedPNL: -$443.08.",
}

CORRECTIONS = {"120": PATCH_120, "158": PATCH_158}


def patch_file(path):
    backup_path = f"{path}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(path, backup_path)
    print(f"Backed up {path} -> {backup_path}")

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    patched_count = 0
    for row in rows:
        op_id = str(row.get("op_id", "")).strip()
        if op_id in CORRECTIONS:
            row.update(CORRECTIONS[op_id])
            patched_count += 1
            print(f"  Patched op_id {op_id} in {path}")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  {patched_count} row(s) patched in {path}\n")
    return patched_count


if __name__ == "__main__":
    total = 0
    for path in FILES_TO_PATCH:
        try:
            total += patch_file(path)
        except FileNotFoundError:
            print(f"  SKIPPED (not found): {path}\n")
    print(f"Done. {total} total row-patches applied across {len(FILES_TO_PATCH)} file(s).")
    print("Refresh the dashboard (or click Refresh in the sidebar) to see corrected numbers.")
