# aula-sync

Unattended sync of UPF **Aula Global** (Moodle) course files and assignments into iCloud Drive
(`~/Library/Mobile Documents/com~apple~CloudDocs/Izobrazba/magisterij/materials`). iCloud then pushes them to the iPad and iPhone.

## What runs where
Everything runs **on the Mac**, as a launchd agent `com.tomibozak.aula-sync`. It runs every 6 h and at login. A run that was due while the Mac slept fires once on wake. It runs at `nice 19` with low-priority I/O, uses one process, and waits 0.3 s between requests.

moodle-dl can't be used: Aula Global has the Moodle mobile web service disabled (`enablemobilewebservice: 0`, and `launch.php` returns 404), so no token is available. `aula_sync.py` therefore logs in like a browser:

1. UPF adAS SSO login with password plus TOTP 2FA (`upf_login.py`).
2. The Moodle AJAX API (`core_course_get_enrolled_courses_by_timeline_classification`, `core_courseformat_get_state`).
3. Activity pages for resources, folders and assignments.

| What | Where |
|---|---|
| Source (this repo) | `~/Projects/EMAI/aula-sync` → github.com/Space0code/aula-sync (private) |
| Installed copy + venv | `~/Library/Application Support/aula-sync/app/` (made by `./install.sh`) |
| Course config | `~/Library/Application Support/aula-sync/courses.json` |
| State (what was downloaded), cookies | `~/Library/Application Support/aula-sync/state.json`, `cookies.pkl` (dir is mode 700) |
| Partial downloads | `~/Library/Caches/aula-sync/*.part`, moved into place only when complete |
| Logs | `~/Library/Logs/aula-sync/aula-sync.log` (rotates at 1 MB, keeps 5); `launchd.err` (crashes only, truncated past 1 MB) |
| Secrets | **Keychain only**: `aula-sync-upf` (U283341 password), `aula-sync-totp` (2FA secret), `aula-sync-gmail` (Gmail app password) |

## What gets synced, and where it lands
**Included:** course files (resources), folders, files embedded in labels, and assignments: the brief (`brief_auto.html`), any attachments, your submission (`submission/`) and feedback (`feedback/`, `feedback_auto.html`).

**Skipped:** forums, links, quizzes, Kaltura videos, books, pages, and video files.

Files go **inside your existing course folders**, sorted into a type subfolder, with the suffix `_auto`:

```
natural_language_interaction/slides/L3_auto.pdf
natural_language_interaction/lab/Extra1_emotion_auto.ipynb        # NLI: code -> lab/
natural_language_interaction/assignments/L4 ASR - Lab Delivery/brief_auto.html
symbolic_reasoning/lectures/S01SR_auto.pdf                        # SR: slides -> lectures/
```

The type subfolders are `slides`, `readings`, `exercises`, `assignments/<name>`, `code` (code and data) and `other`. Files are sorted by extension and filename (`categorize()` in `aula_sync.py`).

Safety rules:
- **Never deletes anything, and only ever writes `*_auto*` files.**
- If a byte-identical copy of a file already exists anywhere in the course folder (e.g. one you downloaded by hand), it is skipped.
- If you delete or move an `_auto` file, it is not downloaded again unless the teacher uploads a new version.
- A changed file on Moodle overwrites its `_auto` copy in place and is reported as `[updated]`.
- Disk guard: a run stops (and emails) if it would download more than 3 GB or leave less than 5 GB free.

## Email
One email goes to bozak.tomi@gmail.com after a run that found new or updated files, listing course → files. No changes means no email.

You also get an email for:
- login failures (wrong password, 2FA rejected),
- crashes,
- the disk guard,
- 48 h without a successful run because of the network.

Each kind of error is emailed at most once per 24 h. If sending fails, the change list is kept and goes out with the next successful email.

The same notifications also go out as **ntfy push** messages to a private topic. The topic name is stored in Keychain as `aula-sync-ntfy` (account `topic`); `security find-generic-password -s aula-sync-ntfy -a topic -w` prints it. Subscribe to it in the ntfy app on the Mac and the iPhone: tap **+**, enter the topic, leave the server as ntfy.sh. Email and ntfy keep separate queues, so a channel that is down or not set up yet catches up later. `aula_sync.py test-ntfy` sends a test push.

## Common tasks
```bash
APP="$HOME/Library/Application Support/aula-sync/app"
"$APP/.venv/bin/python" "$APP/aula_sync.py" run -v         # run now, verbose
"$APP/.venv/bin/python" "$APP/aula_sync.py" run --dry-run  # show what would download
"$APP/.venv/bin/python" "$APP/aula_sync.py" courses        # list courses + folder mapping
"$APP/.venv/bin/python" "$APP/aula_sync.py" test-email
launchctl kickstart gui/$(id -u)/com.tomibozak.aula-sync   # trigger the agent
tail -f ~/Library/Logs/aula-sync/aula-sync.log
```

**Add or exclude a course:** new enrolments are picked up automatically. Each gets a snake_case folder and an entry in `courses.json`. To change a course, edit its entry in `~/Library/Application Support/aula-sync/courses.json`:
- Exclude it: `"include": false`.
- Rename its folder: change `"folder"`.
- Remap a type subfolder: `"subfolders": {"slides": "lectures"}`.

**Pause:** `launchctl bootout gui/$(id -u)/com.tomibozak.aula-sync`. **Resume:** `./install.sh`.

**Update after a code change:** `git pull && ./install.sh`.

**Uninstall:** `./uninstall.sh`. Downloaded files are kept. Add `--purge` to also delete state and logs, and `--purge-secrets` to delete the Keychain items.

## Re-authentication
There's no SSO token to expire. Every run reuses the saved Moodle session, and when that expires it logs in again with the password and a TOTP code generated from the Keychain secret, so normally nothing needs doing. You only act if you **change your UPF password** or **re-enrol 2FA**. You'll know because you get a "login failed" email. To fix it:

1. In the Passwords app: File → Export All Passwords → `~/Downloads/Passwords.csv`.
2. Run `/usr/bin/python3 tools/import_from_apple_passwords.py ~/Downloads/Passwords.csv U283341`. It copies only the `autenticacio.upf.edu` entry (password and TOTP secret) into Keychain and deletes the CSV.

**Gmail app password:** this is a 16-letter code that *Google generates*; a password you make up yourself won't work.
1. Turn on 2-Step Verification (<https://myaccount.google.com/signinoptions/twosv>).
2. Open <https://myaccount.google.com/apppasswords>, name it `aula-sync`, and click Create.
3. In Terminal.app, run `security add-generic-password -U -s aula-sync-gmail -a bozak.tomi@gmail.com -w` and paste the code twice. Spaces don't matter.

Revoke it on the same page at any time.

## Tests
`.venv/bin/python -m unittest discover -s tests` covers naming, categorisation, subfolder overrides, dedupe and the atomic move.
