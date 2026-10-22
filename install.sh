#!/bin/bash
# Install/update aula-sync: copy code to ~/Library/Application Support/aula-sync/app, build its venv,
# and (re)load the launchd agent. Safe to re-run; never touches settings.json, courses.json, state
# or Keychain.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/Library/Application Support/aula-sync"
APP="$BASE/app"
LABEL=local.aula-sync
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$APP" "$HOME/Library/Logs/aula-sync" "$HOME/Library/LaunchAgents"
chmod 700 "$BASE"

if [ ! -f "$BASE/settings.json" ]; then
  cp "$SRC/settings.example.json" "$BASE/settings.json"
  echo "Created $BASE/settings.json. Fill in your UPF user code, email and destination, then re-run ./install.sh"
  exit 1
fi
if grep -q '"U123456"' "$BASE/settings.json"; then
  echo "Edit $BASE/settings.json first (upf_user is still the example U123456), then re-run ./install.sh"
  exit 1
fi

cp "$SRC"/aula_sync.py "$SRC"/upf_login.py "$SRC"/requirements.txt "$APP"/
mkdir -p "$APP/tools" && cp "$SRC"/tools/*.py "$APP/tools/"

if [ ! -x "$APP/.venv/bin/python" ]; then
  /usr/bin/python3 -m venv "$APP/.venv"
fi
"$APP/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"

sed -e "s|__APP__|$APP|g" -e "s|__HOME__|$HOME|g" "$SRC/launchd/$LABEL.plist" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $APP; agent $LABEL loaded (syncs now, then every interval_minutes and at lecture starts; see settings.json)"
