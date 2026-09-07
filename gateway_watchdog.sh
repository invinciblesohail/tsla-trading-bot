#!/bin/bash
# ============================================================================
# Watchdog: checks whether IB Gateway is actually listening on its API port.
# If not, runs the full restart sequence automatically. Meant to run via
# cron every few minutes, so Gateway going down (auto-restart failing,
# a crash, anything) gets self-healed without manual intervention.
#
# Setup (one-time):
#   chmod +x gateway_watchdog.sh
#   crontab -e
#   Add this line (checks every 5 minutes):
#     */5 * * * * /home/mathsdeptsalu/tsla_project/tsla_paper_engine/gateway_watchdog.sh >> /home/mathsdeptsalu/tsla_project/tsla_paper_engine/logs/watchdog.log 2>&1
#
# IMPORTANT: after Gateway restarts, the ENGINE's connection also drops.
# The engine.py reconnect logic (added separately) should recover on its
# own within one poll cycle (60s) - this watchdog only handles Gateway
# itself, not the engine process.
# ============================================================================

GATEWAY_PORT=4002
IBC_START_SCRIPT="$HOME/opt/ibc/gatewaystart.sh"
LOG_PREFIX="[watchdog $(date -u '+%Y-%m-%d %H:%M:%S UTC')]"

if ss -tlnp 2>/dev/null | grep -q ":$GATEWAY_PORT "; then
    echo "$LOG_PREFIX Gateway is up on port $GATEWAY_PORT - nothing to do."
    exit 0
fi

echo "$LOG_PREFIX Gateway NOT listening on port $GATEWAY_PORT - restarting..."

sudo pkill -f Xvfb 2>/dev/null
sudo pkill -f java 2>/dev/null
sudo rm -f /tmp/.X*-lock
sleep 2

Xvfb :99 -screen 0 1024x768x24 &
sleep 5
export DISPLAY=:99
"$IBC_START_SCRIPT" &

echo "$LOG_PREFIX Restart sequence launched, waiting 90s to confirm..."
sleep 90

if ss -tlnp 2>/dev/null | grep -q ":$GATEWAY_PORT "; then
    echo "$LOG_PREFIX Gateway successfully restarted and listening on port $GATEWAY_PORT."
else
    echo "$LOG_PREFIX WARNING: Gateway still not listening after restart attempt. Manual check needed."
fi
