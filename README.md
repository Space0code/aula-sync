# aula-sync

Unattended sync of your **UPF Aula Global** (Moodle) course files and assignments into a folder on your Mac, by default in iCloud Drive so the files also reach your iPad and iPhone. When new files arrive, you get a short summary by email and/or ntfy push.

> Unofficial tool. It logs in as you, with your own UPF account, and only downloads what you can already see in the browser. Requests are spaced out and it syncs every 30 minutes in the daytime (configurable) and at each lecture start.

## Why not moodle-dl?
Aula Global has the Moodle mobile web service turned off (`enablemobilewebservice: 0`, and `admin/tool/mobile/launch.php` returns 404), so there is no token for moodle-dl or the Moodle app. `aula_sync.py` logs in like a browser instead:

1. UPF's adAS single sign-on, with your password and TOTP two-factor code (`upf_login.py`).
2. The Moodle AJAX API (`core_course_get_enrolled_courses_by_timeline_classification`, `core_courseformat_get_state`).
3. The activity pages for resources, folders and assignments.

## What gets synced
- **Included:** course files (resources), folders, files embedded in labels, and assignments: the brief (`brief_auto.html`), its attachments, your submission (`submission/`) and the feedback (`feedback/`, `feedback_auto.html`).
- **Forums (notice boards):** checked for new posts, not downloaded; see Notifications.
- **Skipped:** links, quizzes, Kaltura videos, books, pages, and video files.

Files land in `<destination>/<course folder>/<type>/<name>_auto.<ext>`:

```
natural_language_interaction/slides/L3_auto.pdf
natural_language_interaction/lab/Extra1_emotion_auto.ipynb        # "code" remapped to lab/
natural_language_interaction/assignments/L4 ASR - Lab Delivery/brief_auto.html
symbolic_reasoning/lectures/S01SR_auto.pdf                        # "slides" remapped to lectures/
```

The type folders are `slides`, `readings`, `exercises`, `assignments/<name>`, `code` (code and data) and `other`. Files are sorted by extension and filename; see `categorize()` in `aula_sync.py`.

**Safe to point at a folder you already use:**
- It never deletes anything, and it only ever writes `*_auto*` files.
- It skips a file if you already have a byte-identical copy anywhere in that course's folder.
- If you delete or move an `_auto` file, it isn't downloaded again unless the teacher uploads a new version.
- A new version from Moodle replaces its `_auto` copy only if you haven't edited that copy (for example, annotated it on the iPad). Otherwise the new version is saved alongside it as `name_auto (2).ext`.
- Downloads are written to a temporary file first and moved into place only when complete.
- Disk guard: a run stops, and alerts you, if it would download more than 3 GB or leave less than 5 GB free.

## Requirements
- macOS with `/usr/bin/python3` (the Xcode Command Line Tools provide it).
- A UPF account with two-factor authentication through an authenticator app (TOTP), with access to its secret (see step 3).
- Optional: a Gmail account for email alerts, and/or the [ntfy](https://ntfy.sh) app for push notifications.

## Setup
1. **Clone the repo and create your settings:**
   ```bash
   git clone https://github.com/Space0code/aula-sync.git && cd aula-sync
   ./install.sh        # first run only creates ~/Library/Application Support/aula-sync/settings.json
   ```
2. **Edit `~/Library/Application Support/aula-sync/settings.json`.** This file stays on your Mac and is never committed.

   | Key | Meaning | Example |
   |---|---|---|
   | `upf_user` | the user code you type on the UPF login page (not your email) | `"U123456"` |
   | `email` | Gmail address that sends and receives the alerts; `""` turns email off | `"you@gmail.com"` |
   | `destination` | folder for the synced files (`~` allowed); create it first | `"~/Library/Mobile Documents/com~apple~CloudDocs/Aula Global"` |
   | `sync_windows` | optional: `[from, to, every_minutes]` in local time, both ends included; no syncs outside them (default: every 30 min 08:00–16:00, every 2 h 16:00–20:00) | `[["08:00", "16:00", 30], ["16:00", "20:00", 120]]` |
   | `calendar_url` | optional: iCalendar feed of your timetable; a sync also runs at each lecture start | `"https://…/upf.ics"` |
   | `forum_alerts` | optional: which new forum posts to alert about: `"unsubscribed"` (default: only posts Moodle won't email you itself), `"all"`, or `"off"` | `"unsubscribed"` |
   | `lecture_offsets_minutes` | optional: minutes after each lecture start to sync (default `[0, 15]`; negative = before) | `[0, 15]` |

3. **Store your UPF password and TOTP secret in Keychain.** Pick one:
   - **The code comes from Apple Passwords** (the Passwords app or iCloud Keychain fills it in):
     1. In the Passwords app, choose File → Export All Passwords and save it as `~/Downloads/Passwords.csv`.
     2. Run `/usr/bin/python3 tools/import_from_apple_passwords.py ~/Downloads/Passwords.csv`. It copies only the `autenticacio.upf.edu` entry and then deletes the CSV.
   - **The code comes from another authenticator app:** you need the TOTP *setup key* (the base32 text behind the QR code). If you don't have it, re-enrol 2FA at UPF and save the key this time. Then, in Terminal.app, run each command and type or paste the value at the hidden prompt:
     ```bash
     security add-generic-password -U -s aula-sync-upf  -a U123456 -w   # your UPF password
     security add-generic-password -U -s aula-sync-totp -a U123456 -w   # the TOTP setup key
     ```
4. **Optional: email alerts.** Gmail needs an *app password*, a 16-letter code that Google generates; one you make up won't work.
   1. Turn on 2-Step Verification at <https://myaccount.google.com/signinoptions/twosv>.
   2. Create the app password at <https://myaccount.google.com/apppasswords>.
   3. Store it:
      ```bash
      security add-generic-password -U -s aula-sync-gmail -a you@gmail.com -w   # paste the code; spaces are ignored
      ```
5. **Optional: ntfy push notifications.** Pick a random, private topic name. Anyone who knows it can read your notifications.
   ```bash
   T="aula-sync-$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(8))')"; echo "$T"
   security add-generic-password -U -s aula-sync-ntfy -a topic -w "$T"
   ```
   In the ntfy app on each device, tap **+**, enter the topic and leave the server as ntfy.sh.
6. **Preview, then install:**
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python aula_sync.py run --dry-run   # lists what would be downloaded, with sizes
   ./install.sh                                  # installs the agent and starts the first sync
   ```
   The dry run also writes `courses.json` with an automatic folder name for each course. Edit it before installing if you like (see *Courses* below).

## Notifications
- **New or updated files:** one message after each run that found something, grouped by course and type (an HTML email plus a plain-text ntfy push). No changes, no message. A saved page (assignment `brief.html`, `feedback.html`) counts as changed only when its visible text or links change, not when Moodle re-renders its markup.
- **Forum posts:** Moodle already emails you every post in a discussion you're subscribed to (notice boards are subscribed by default). Each run checks every course forum and alerts you once about a new post Moodle won't email you, with its text and a link. The first check of a forum only records the posts already there. `forum_alerts` changes the rule.
- **Problems:** you get an alert for a login failure (e.g. you changed your password or re-enrolled 2FA), a crash, the disk guard, or 48 h without a successful run because of the network. Each kind of problem is reported at most once per 24 h.
- **Queues:** email and ntfy keep separate queues, so a channel that is down or not set up yet catches up later.

## Courses
New enrolments are picked up automatically. Each course gets a snake_case folder name and an entry in `~/Library/Application Support/aula-sync/courses.json`. To change a course, edit its entry:
- `"include": false` excludes it.
- `"folder"` sets its folder name, e.g. to match a folder you already have.
- `"subfolders": {"slides": "lectures", "code": "lab"}` renames type folders for that course.

`courses.example.json` shows a full example.

## What runs where
Everything runs on your Mac, as the launchd agent `local.aula-sync`:
- launchd starts `aula_sync.py tick` every 5 min and at login. The tick syncs only when a slot has passed since the last sync: a `sync_windows` time (08:00, 08:30, … 16:00, 18:00, 20:00 by default) or a lecture start from `calendar_url` plus `lecture_offsets_minutes`; otherwise it exits at once. Nothing runs at night. The feed is cached in `calendar.ics` and refreshed every 6 h. A slot missed while the Mac slept is caught up once on wake.
- Changing `sync_windows`, `calendar_url` or `lecture_offsets_minutes` takes effect at the next tick; no reinstall needed. `aula_sync.py schedule` prints the windows and the next sync times.
- It runs at `nice 19` with low-priority I/O, as a single process with 0.3 s between requests.

| What | Where |
|---|---|
| Installed code and its venv | `~/Library/Application Support/aula-sync/app/` (copied by `./install.sh`) |
| Your settings and course config | `~/Library/Application Support/aula-sync/settings.json`, `courses.json` |
| State (what was downloaded) and session cookies | `~/Library/Application Support/aula-sync/state.json`, `cookies.pkl` (the directory is mode 700) |
| Partial downloads | `~/Library/Caches/aula-sync/` |
| Logs | `~/Library/Logs/aula-sync/aula-sync.log` (rotates at 1 MB, keeps 5); `launchd.err` (crashes only) |
| Secrets | macOS Keychain only: `aula-sync-upf`, `aula-sync-totp`, `aula-sync-gmail`, `aula-sync-ntfy` |

## Everyday commands
```bash
APP="$HOME/Library/Application Support/aula-sync/app"
"$APP/.venv/bin/python" "$APP/aula_sync.py" run -v              # sync now, verbose
"$APP/.venv/bin/python" "$APP/aula_sync.py" run --dry-run       # what would be downloaded
"$APP/.venv/bin/python" "$APP/aula_sync.py" schedule            # interval and next lecture triggers
"$APP/.venv/bin/python" "$APP/aula_sync.py" courses             # courses and folder mapping
"$APP/.venv/bin/python" "$APP/aula_sync.py" test-email --with-error
"$APP/.venv/bin/python" "$APP/aula_sync.py" test-ntfy
launchctl kickstart gui/$(id -u)/local.aula-sync                # trigger the agent
tail -f ~/Library/Logs/aula-sync/aula-sync.log
```

- **Pause:** `launchctl bootout gui/$(id -u)/local.aula-sync`. To resume, run `./install.sh`.
- **Update:** `git pull && ./install.sh`.
- **Uninstall:** `./uninstall.sh` keeps the downloaded files. Add `--purge` to also delete settings, state and logs, and `--purge-secrets` to delete the Keychain items.

## Re-authentication
There's no token to expire. Each run reuses the saved Moodle session; when that expires, the script logs in again with your password and a fresh TOTP code. You only need to act after you **change your UPF password** or **re-enrol 2FA**, and a "can't log in" alert tells you. To fix it, redo step 3 of Setup.

## Development
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python upf_login.py U123456          # login test only
```
The tests cover naming, categorisation, subfolder overrides, dedupe, the no-overwrite rules, email rendering, the atomic move, page change detection, forum alerts and the schedule.

## License
MIT
