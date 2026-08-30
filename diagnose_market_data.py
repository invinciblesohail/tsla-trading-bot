"""
Standalone diagnostic: tests whether this IBKR paper account has LIVE market
data permissions for TSLA, isolated from the full engine. Historical data
(warmup) and live streaming often draw on different entitlements - this
checks the live side directly, which is where the engine has been silently
getting nothing.

Run with: python3 diagnose_market_data.py
"""

from ib_insync import IB, Contract, util

ib = IB()
ib.connect("127.0.0.1", 4002, clientId=250, timeout=15)

contract = Contract(secType="STK", symbol="TSLA", exchange="SMART", currency="USD")
ib.qualifyContracts(contract)
print(f"Contract qualified: {contract}\n")

print("=" * 60)
print("TEST 1: Live streaming market data (reqMktData)")
print("=" * 60)
ticker = ib.reqMktData(contract, "", False, False)
ib.sleep(5)
print(f"Bid: {ticker.bid}  Ask: {ticker.ask}  Last: {ticker.last}")
print(f"Market data type in use: {ticker.marketDataType}  "
      f"(1=live, 2=frozen, 3=delayed, 4=delayed-frozen)")
if ticker.bid != ticker.bid or ticker.last != ticker.last:  # NaN check
    print(">>> No live price data received - likely a permissions gap.")
ib.cancelMktData(contract)
print()

print("=" * 60)
print("TEST 2: Explicitly request DELAYED data (fallback tier)")
print("=" * 60)
ib.reqMarketDataType(3)  # 3 = delayed
ticker2 = ib.reqMktData(contract, "", False, False)
ib.sleep(5)
print(f"Bid: {ticker2.bid}  Ask: {ticker2.ask}  Last: {ticker2.last}")
if ticker2.bid == ticker2.bid or ticker2.last == ticker2.last:  # not NaN
    print(">>> Delayed data DOES work - confirms this is a live-data "
          "subscription gap specifically, not a total data blackout.")
else:
    print(">>> Even delayed data failed - broader issue, not just a live-tier gap.")
ib.cancelMktData(contract)
print()

print("=" * 60)
print("TEST 3: Live 5-min bars via reqRealTimeBars (a different API path)")
print("=" * 60)
ib.reqMarketDataType(1)  # back to live
bars = ib.reqRealTimeBars(contract, 5, "TRADES", False)
ib.sleep(10)
print(f"Real-time bars received so far: {len(bars)}")
if len(bars) == 0:
    print(">>> No real-time bars either - consistent with a live equity "
          "market data permission gap on this account.")
ib.cancelRealTimeBars(bars)

print()
print("Any errors printed above by ib_insync itself (e.g. 'Error 354',")
print("'requires additional subscription') are the most direct evidence -")
print("scroll up and check for those specifically.")

ib.disconnect()
