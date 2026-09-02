# TSLA 3-Factor Paper Trading Bot

Automated paper-trading system for a TSLA 3-Factor strategy (Trend 15% /
Bollinger 50% / Operating Space 35%), running live against Interactive
Brokers via `ib_insync`. Built for a 2-week baseline validation run, per
client spec.

## What this actually does

- Connects to IB Gateway, polls TSLA 5-min bars every 60 seconds (NOT
  push-based `keepUpToDate` - see "Known Issues" below for why).
- Evaluates every closed bar against the validated strategy logic
  (`tsla_3factor_CORRECTED.py`), classifying each as ENTRY, NO-ENTRY (with
  a specific blocking reason), or NO-SETUP.
- On ENTRY: sizes the position via risk-based sizing (1% of balance ÷
  ATR-based stop distance), places a real IBKR bracket order (market entry
  + OCA stop/limit), and logs the decision.
- Logs every single decision (not just trades) to CSV, per the client's
  33-column logging spec (`Spec_Logging_CSV_TSLA_EN.docx`).
- Sends real-time Telegram alerts on trade open/close, plus `/export` and
  `/status` commands for on-demand reporting.
- Serves a Streamlit dashboard (dark theme, login-gated) showing live
  status, open/closed trades, and decision-log analysis.
- Self-heals: a cron watchdog restarts IB Gateway if it goes down, and the
  engine detects and recovers from dropped IBKR connections automatically.

## Architecture

```
tsla_bot/
  config.py            - ALL settings (NOT in git - see config.example.py)
  config.example.py    - template with secrets blanked out
  decision_logger.py   - 33-column CSV writer (ENTRY/NO-ENTRY/NO-SETUP)
  engine.py            - IBKR connection, polling loop, order management
  alerts.py            - real-time Telegram trade-open/close alerts
  telegram_bot.py      - /export and /status commands, daily summary fn
  dashboard.py         - Streamlit dashboard
tsla_3factor_CORRECTED.py  - validated strategy logic (imported by engine.py)
gateway_watchdog.sh   - cron script: restarts Gateway if its port goes down
start_tsla_bot.sh     - tmux launcher: starts engine+telegram+dashboard in one command
diagnose_market_data.py    - standalone script to test IBKR market data permissions
diagnose_keepuptodate.py   - standalone script to test keepUpToDate bar delivery
```

## Setup on a NEW VPS (e.g. after migration)

### 1. Base system
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y openjdk-17-jdk xvfb x11-utils xterm \
    libxrender1 libxtst6 libxi6 libxrandr2 libxss1 \
    libgtk-3-0 libgl1-mesa-glx libglu1-mesa mesa-utils \
    tmux cron iproute2
sudo systemctl enable cron && sudo systemctl start cron
```
The GTK/mesa libraries are NOT optional - IB Gateway 10.45+ uses JavaFX,
which crashes with "Unable to load glass GTK library" without them (cost
real debugging time to find - see Known Issues).

### 2. Python
```bash
# Python 3.12 via deadsnakes PPA if not already on 22.04+/24.04
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### 3. Clone this repo
```bash
git clone https://github.com/yourusername/tsla-trading-bot.git
cd tsla-trading-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Recreate config.py from the template
```bash
cp tsla_bot/config.example.py tsla_bot/config.py
nano tsla_bot/config.py
```
Fill in real values for `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`DASHBOARD_PASSWORD`. See `tsla_bot/telegram_bot.py` docstring for how to
get a Telegram token/chat ID via @BotFather.

### 5. Install IB Gateway + IBC (this is the part that took the longest to
### get right the first time - follow exactly)

```bash
mkdir -p ~/tsla_project/Jts ~/tsla_project/opt/ibc
cd ~/tsla_project
wget "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh" -O ibgateway_installer.sh
chmod +x ibgateway_installer.sh
./ibgateway_installer.sh -q -dir ~/tsla_project/Jts -console
```

Download IBC:
```bash
cd ~/tsla_project/opt/ibc
wget "https://github.com/IbcAlpha/IBC/releases/download/3.23.0/IBCLinux-3.23.0.zip"
unzip -o IBCLinux-3.23.0.zip
chmod +x *.sh scripts/*.sh
```

**Fix the directory structure** (IB Gateway installs flat, IBC expects a
version-numbered subfolder):
```bash
ls ~/tsla_project/Jts/ibgateway   # find the actual installed version
mv ~/tsla_project/Jts/ibgateway ~/tsla_project/Jts/ibgateway_bin
mkdir -p ~/tsla_project/Jts/ibgateway/<VERSION>   # e.g. 1045
cp -r ~/tsla_project/Jts/jars ~/tsla_project/Jts/ibgateway/<VERSION>/
cp -r ~/tsla_project/Jts/.install4j ~/tsla_project/Jts/ibgateway/<VERSION>/
cp ~/tsla_project/Jts/ibgateway.vmoptions ~/tsla_project/Jts/ibgateway/<VERSION>/
```

**Configure `~/tsla_project/opt/ibc/config.ini`** (see the full annotated
version shipped with IBC for all options - these are the ones that
actually matter):
```ini
IbLoginId=YOUR_IB_USERNAME
IbPassword=YOUR_IB_PASSWORD
TradingMode=paper
FIX=no
ReadOnlyApi=no
AcceptIncomingConnectionAction=accept
OverrideTwsApiPort=4002
AutoRestartTime=00:30
AcceptNonBrokerageAccountWarning=yes
```
**`AcceptNonBrokerageAccountWarning=yes` is CRITICAL** - without it, IBC
cannot auto-dismiss the paper-trading disclaimer dialog, and the API will
reject every connection with `Error 10141` forever, with no obvious fix
(cost a full day to diagnose - see Known Issues).

**Configure `gatewaystart.sh`** with your paths, version number, and
credentials (see the file itself for the exact fields to fill in).

**Patch `ibc/scripts/ibcstart.sh`** - IBC strips all `-D` Java options from
Gateway's own vmoptions file, but Gateway 10.45+ needs two of them back.
Find this line:
```
java_vm_options="$java_vm_options -Dibcsessionid=$ibc_session_id"
```
And add immediately after it:
```
java_vm_options="$java_vm_options -DinstallDir=${program_path}"
java_vm_options="$java_vm_options -DvmOptionsPath=${program_path}/ibgateway.vmoptions"
```
Without this, IBC can't properly interact with Gateway's JavaFX dialogs
even with AcceptNonBrokerageAccountWarning set correctly.

### 6. First-time login (must be done via a real display, not headless)

The very first login to a new IP/device may trigger IBKR's 2FA or an
"IP not authorized" block that headless IBC cannot handle. Options:
- Set up a graphical remote desktop (Chrome Remote Desktop is simplest) or
  RDP, launch `~/tsla_project/Jts/ibgateway_bin` directly (NOT via IBC) to
  see the actual login window, complete 2FA/whitelist your VPS's IP in
  IBKR Client Portal if needed, and confirm you reach the main Gateway
  window successfully.
- **Only ONE Gateway instance can hold port 4002 at a time** - if you test
  manually via GUI, fully close it (File > Exit) before starting the
  headless IBC version, or you'll get silent confusion about which
  instance you're actually talking to.

### 7. Start everything with one command
```bash
cd ~/tsla-trading-bot
chmod +x start_tsla_bot.sh gateway_watchdog.sh
./start_tsla_bot.sh
```
This starts `engine`, `telegram`, and `dashboard` in a tmux session named
`tsla`. Gateway itself needs to be started separately first (see step 6) -
consider adding it as a 4th tmux window using the same `Xvfb + gatewaystart.sh`
sequence, run once.

### 8. Set up the watchdog
```bash
crontab -e
```
Add:
```
*/5 * * * * /home/YOURUSER/tsla-trading-bot/gateway_watchdog.sh >> /home/YOURUSER/tsla-trading-bot/logs/watchdog.log 2>&1
```

### 9. Verify end-to-end
```bash
ss -tlnp | grep 4002          # Gateway listening?
tmux list-windows -t tsla     # all 3 windows present?
tail -20 logs/tsla_engine.log # clean startup, no tracebacks?
```

## Known issues / hard-won lessons (read before debugging blind)

1. **Delayed market data, not live.** This account doesn't have a live US
   equity market data subscription. `MARKET_DATA_TYPE=3` in config.py.
   Confirmed live: `keepUpToDate=True` historical bars deliver ZERO
   updates under delayed data, even during active market hours - this is
   why the engine POLLS every 60s instead of using push updates.

2. **Bracket orders MUST set `tif="GTC"` explicitly.** Confirmed live:
   without this, IBKR's account preset silently forces `tif=DAY`, and DAY
   orders expire at end-of-session - this left a real position with ZERO
   stop/target protection overnight, losing -$443 (roughly 4x the
   intended risk) before being caught. Fixed in engine.py; if this
   recurs, check for `Error 10349` in the log.

3. **Entry price must be corrected to the real fill, not the delayed-data
   signal price.** The first live trade showed a 17x PnL discrepancy
   (logged: $124.96, IBKR's actual realizedPNL: $7.41) before this was
   fixed. `engine.py` now listens for the parent order's fill and patches
   the already-logged CSV row via `decision_logger.update_entry_fill()`.

4. **`ib.reqHistoricalData()` (sync) cannot be called from inside a
   coroutine already running on ib_insync's event loop** - throws "This
   event loop is already running". Always use the `...Async` variant
   (`reqHistoricalDataAsync`, `connectAsync`, `qualifyContractsAsync`)
   inside anything scheduled via `asyncio.ensure_future()`.

5. **The IB Gateway "paper trading disclaimer" dialog is JavaFX-based**
   and won't be auto-dismissed by IBC without both
   `AcceptNonBrokerageAccountWarning=yes` in config.ini AND the
   `ibcstart.sh` patch for `-DinstallDir`/`-DvmOptionsPath` (see step 5
   above). Symptom without both: `Error 10141` forever, Gateway listens
   on the port but rejects every API connection.

6. **`.streamlit/config.toml` is read relative to the CURRENT WORKING
   DIRECTORY `streamlit run` is invoked from**, not the script's location.
   Keep it at the repo root.

7. **Dashboard `dashboard.py` needs an explicit `sys.path` fix** at the
   top (adds its own parent directory) because Streamlit only adds the
   script's own folder to the path by default, not the package root.

8. **pandas version gotchas** (this account runs pandas 3.x): use
   `.astype(str)` on BOTH sides of a string concatenation (not just one),
   and use `.style.map()` not the removed `.style.applymap()`.

## Migrating to a new VPS - checklist

- [ ] `git clone` this repo on the new VPS
- [ ] Recreate `tsla_bot/config.py` from `config.example.py` with real secrets
- [ ] Full IB Gateway + IBC setup (steps 1-6 above) - this is the slow part
- [ ] First-time login via graphical desktop to clear 2FA/disclaimer/IP whitelist
- [ ] `start_tsla_bot.sh` + cron watchdog
- [ ] Update IBKR's IP whitelist (Client Portal) to the NEW VPS's IP if IP
      restriction is enabled on the account
- [ ] Verify a full day of clean polling before trusting it unattended

## Data / paper-run integrity notes

- `PAPER_RUN_LOCKED = True` in config.py is a documentation flag, not a
  runtime lock - the actual discipline of not changing strategy
  parameters mid-run is manual, per the client's explicit instruction.
- The first trade's logged PnL ($124.96) is KNOWN INCORRECT - real value
  per IBKR is $7.41 (see Known Issue #3). Not retroactively fixed in the
  CSV; note this when reporting cumulative results from early in the run.
- The second trade lost -$443.08 (confirmed via IBKR's realizedPNL) due
  to Known Issue #2 (TIF/GTC bug), now fixed. This was a real bug-driven
  loss, not the strategy underperforming - worth excluding or footnoting
  when evaluating the strategy's actual edge from this baseline period.
