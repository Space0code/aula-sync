#!/bin/bash
# Stop and remove the launchd agent and installed code. Keeps downloaded files, and by default
# also keeps state/config (pass --purge to delete them, plus Keychain items with --purge-secrets).
set -uo pipefail
LABEL=com.tomibozak.aula-sync
BASE="$HOME/Library/Application Support/aula-sync"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "agent stopped"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$BASE/app"
for a in "$@"; do
  case "$a" in
    --purge) rm -rf "$BASE" "$HOME/Library/Caches/aula-sync" "$HOME/Library/Logs/aula-sync"; echo "state/logs removed" ;;
    --purge-secrets)
      security delete-generic-password -s aula-sync-upf -a U283341 >/dev/null 2>&1
      security delete-generic-password -s aula-sync-totp -a U283341 >/dev/null 2>&1
      security delete-generic-password -s aula-sync-gmail -a bozak.tomi@gmail.com >/dev/null 2>&1
      echo "Keychain items removed" ;;
  esac
done
echo "uninstalled (downloaded *_auto files left in place)"
