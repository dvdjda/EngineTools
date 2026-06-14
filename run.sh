#!/usr/bin/env zsh
# EngineTools launcher — self-detaching.
# Frees the terminal immediately; app runs in background.
# Log: /tmp/enginetools.log

_SCRIPT="/Users/dvdj/EngineTools/run.sh"
_APPDIR="/Users/dvdj/EngineTools"
_PY="/opt/anaconda3/bin/python3"          # Anaconda Python — has CoolProp + all deps
_ZSH="${SHELL:-/bin/zsh}"

# --- self-detach on first call ---
if [[ -z "$_ET_BG" ]]; then
  _ET_BG=1 nohup "$_ZSH" "$_SCRIPT" >> /tmp/enginetools.log 2>&1 &
  disown
  echo "EngineTools starting in background."
  echo "  App : http://127.0.0.1:8050  (browser tab opens automatically)"
  echo "  Log : tail -f /tmp/enginetools.log"
  exit 0
fi

# ---- background process from here ----
echo "=== EngineTools starting $(date) ==="

# load shell profile (conda, API keys)
[[ -f /Users/dvdj/.zshrc ]] && source /Users/dvdj/.zshrc 2>/dev/null

# --- Anthropic key from macOS Keychain ---
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  for _svc in "openclaw" "OpenClaw" "openclaw-keys" "openclaw-auth"; do
    for _acc in "anthropic:default" "anthropic" "ANTHROPIC_API_KEY" "default" "api_key"; do
      _key=$(security find-generic-password -s "$_svc" -a "$_acc" -w 2>/dev/null)
      if [[ -n "$_key" ]]; then
        export ANTHROPIC_API_KEY="$_key"
        echo "Anthropic key loaded (service=$_svc account=$_acc)"
        unset _key
        break 2
      fi
    done
  done
fi

cd "$_APPDIR"

# kill any existing instance
lsof -ti:8050 | xargs kill -9 2>/dev/null
sleep 1

# open browser tab once the app is serving
( until nc -z 127.0.0.1 8050 2>/dev/null; do sleep 0.5; done; open "http://127.0.0.1:8050" ) &

PYTHONPATH="$_APPDIR" "$_PY" -m nexa_toolkit.app.app
echo "=== EngineTools stopped $(date) ==="
