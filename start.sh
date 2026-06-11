#!/usr/bin/env bash
# EngineTools — start the Dash app in the background (survives terminal close)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="$SCRIPT_DIR/enginetools.log"
PIDFILE="$SCRIPT_DIR/enginetools.pid"

# Check if already running
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "EngineTools is already running (PID $PID)."
        echo "Use ./stop.sh to stop it first, or ./restart.sh to restart."
        exit 0
    else
        rm -f "$PIDFILE"
    fi
fi

cd "$SCRIPT_DIR"
# Use Anaconda Python (has CoolProp, pythonnet, all required packages)
PYTHON=/opt/anaconda3/bin/python3
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
nohup "$PYTHON" -m nexa_toolkit.app.app > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

echo "EngineTools started (PID $(cat $PIDFILE))"
echo "UI:  http://localhost:8050"
echo "Log: $LOGFILE"
echo "Stop: ./stop.sh"
