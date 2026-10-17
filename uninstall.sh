#!/bin/bash
# Stop and remove the launchd agent and installed code. Downloaded files are always kept.
#   --purge          also delete settings, course config, state and logs
#   --purge-secrets  also delete the aula-sync Keychain items
set -uo pipefail
LABEL=local.aula-sync
BASE="$HOME/Library/Application Support/aula-sync"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "agent $LABEL stopped"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$BASE/app"
for a in "$@"; do
  case "$a" in
    --purge) rm -rf "$BASE" "$HOME/Library/Caches/aula-sync" "$HOME/Library/Logs/aula-sync"; echo "settings/state/logs removed" ;;
    --purge-secrets)
      for s in aula-sync-upf aula-sync-totp aula-sync-gmail aula-sync-ntfy; do
        while security delete-generic-password -s "$s" >/dev/null 2>&1; do :; done
      done
      echo "Keychain items removed" ;;
  esac
done
echo "uninstalled (downloaded *_auto files left in place)"
