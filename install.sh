#!/bin/bash
# Install/update aula-sync: copy code to ~/Library/Application Support/aula-sync/app, build its venv,
# and (re)load the launchd agent. Safe to re-run; never touches courses.json, state or Keychain.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/Library/Application Support/aula-sync"
APP="$BASE/app"
LABEL=com.tomibozak.aula-sync
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$APP" "$HOME/Library/Logs/aula-sync" "$HOME/Library/LaunchAgents"
chmod 700 "$BASE"
cp "$SRC"/aula_sync.py "$SRC"/upf_login.py "$SRC"/courses.default.json "$SRC"/requirements.txt "$APP"/
mkdir -p "$APP/tools" && cp "$SRC"/tools/*.py "$APP/tools/"
[ -f "$BASE/courses.json" ] || cp "$SRC/courses.default.json" "$BASE/courses.json"

if [ ! -x "$APP/.venv/bin/python" ]; then
  /usr/bin/python3 -m venv "$APP/.venv"
fi
"$APP/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"

sed -e "s|__APP__|$APP|g" -e "s|__HOME__|$HOME|g" "$SRC/launchd/$LABEL.plist" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $APP; agent $LABEL loaded (runs now, then every 6 h)"
