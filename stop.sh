#!/usr/bin/env bash
# EngineTools — stop the background Dash app

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$SCRIPT_DIR/enginetools.pid"

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm -f "$PIDFILE"
        echo "EngineTools stopped (PID $PID)."
    else
        rm -f "$PIDFILE"
        echo "Process was not running. PID file cleaned up."
    fi
else
    # Fallback: kill by port
    PID=$(lsof -ti:8050 2>/dev/null)
    if [ -n "$PID" ]; then
        kill "$PID"
        echo "EngineTools stopped (PID $PID, found via port 8050)."
    else
        echo "EngineTools is not running."
    fi
fi
