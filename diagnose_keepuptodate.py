"""
Isolates ONE specific question: does reqHistoricalData(..., keepUpToDate=True)
actually receive new bars under DELAYED market data, independent of the full
engine. Connects, subscribes exactly like engine.py does, then just watches
and prints the bar count every 10 seconds for 2 minutes.

Run with: python3 diagnose_keepuptodate.py
"""

from ib_insync import IB, Contract, util

ib = IB()
ib.connect("127.0.0.1", 4002, clientId=251, timeout=15)
ib.reqMarketDataType(3)  # delayed

contract = Contract(secType="STK", symbol="TSLA", exchange="SMART", currency="USD")
ib.qualifyContracts(contract)
print(f"Contract qualified: {contract}\n")

bars = ib.reqHistoricalData(
    contract,
    endDateTime="",
    durationStr="1 D",
    barSizeSetting="5 mins",
    whatToShow="TRADES",
    useRTH=False,
    formatDate=2,
    keepUpToDate=True,
)

print(f"Initial bar count: {len(bars)}")
if len(bars) > 0:
    print(f"Most recent bar: {bars[-1]}")
print()

update_count = 0


def on_update(bars, has_new_bar):
    global update_count
    update_count += 1
    print(f"[UPDATE #{update_count}] has_new_bar={has_new_bar}, "
          f"total_bars={len(bars)}, last_bar_time={bars[-1].date if len(bars) else None}")


bars.updateEvent += on_update

print("Watching for 2 minutes - any update at all (even has_new_bar=False, "
      "which fires on live ticks to the forming bar) will print above...")
print()

for i in range(12):
    ib.sleep(10)
    print(f"  [{(i+1)*10}s elapsed] total updateEvent firings so far: {update_count}, "
          f"bar list length: {len(bars)}")

print()
if update_count == 0:
    print(">>> ZERO update events fired in 2 minutes. keepUpToDate is not "
          "delivering ANY updates under delayed data - this confirms a real "
          "incompatibility, not just a timing issue.")
else:
    print(f">>> {update_count} updates fired - keepUpToDate IS working under "
          f"delayed data. The issue must be somewhere else in the engine's "
          f"processing, not the data subscription itself.")

ib.disconnect()
