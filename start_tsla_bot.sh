#!/bin/bash
# ============================================================================
# Starts the full TSLA bot stack (engine, telegram_bot, dashboard) inside a
# single tmux session, each in its own window. Once started, closing your
# SSH terminal does NOT stop any of these - they keep running on the VPS.
#
# Usage:
#   ./start_tsla_bot.sh
#
# To view/attach:
#   tmux attach -t tsla
#   (Ctrl+B then D to detach again without stopping anything)
#
# To check status without attaching:
#   tmux list-windows -t tsla
#
# To stop everything:
#   tmux kill-session -t tsla
# ============================================================================

SESSION="tsla"
PROJECT_DIR="$HOME/tsla_project/tsla_paper_engine"
VENV_ACTIVATE="$HOME/tsla_project/.venv/bin/activate"

# If the session already exists, don't create duplicates - just tell the
# user how to attach instead.
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "A tmux session named '$SESSION' already exists."
    echo "Attach with: tmux attach -t $SESSION"
    echo "Or stop it first with: tmux kill-session -t $SESSION"
    exit 1
fi

# Guard against clientId collisions (same issue seen earlier): kill any
# bare (non-tmux) engine process still running before starting a fresh one.
if pgrep -f "tsla_bot.engine" > /dev/null; then
    echo "Found an existing tsla_bot.engine process outside tmux - stopping it first..."
    pkill -f "tsla_bot.engine"
    sleep 2
fi

echo "Starting tmux session '$SESSION' with 3 windows: engine, telegram, dashboard..."

# Window 1: engine
tmux new-session -d -s "$SESSION" -n engine -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION:engine" "source $VENV_ACTIVATE && python3 -m tsla_bot.engine" C-m

# Window 2: telegram_bot
tmux new-window -t "$SESSION" -n telegram -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION:telegram" "source $VENV_ACTIVATE && python3 -m tsla_bot.telegram_bot" C-m

# Window 3: dashboard
tmux new-window -t "$SESSION" -n dashboard -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION:dashboard" "source $VENV_ACTIVATE && streamlit run tsla_bot/dashboard.py --server.address 0.0.0.0 --server.port 8501" C-m

echo ""
echo "All 3 windows started. Session will keep running after you disconnect."
echo ""
echo "  Attach and view:   tmux attach -t $SESSION"
echo "  Switch windows:    Ctrl+B then window number (0=engine, 1=telegram, 2=dashboard)"
echo "  Detach (keep running): Ctrl+B then D"
echo "  List windows:      tmux list-windows -t $SESSION"
echo "  Stop everything:   tmux kill-session -t $SESSION"
echo ""
tmux list-windows -t "$SESSION"
