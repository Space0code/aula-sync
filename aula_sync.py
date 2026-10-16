#!/usr/bin/env python3
"""Sync UPF Aula Global (Moodle) course files + assignments into iCloud Drive.

Usage:
  aula_sync.py run [--dry-run]   sync (dry run: list what would be downloaded, with sizes)
  aula_sync.py test-email        send a test email
  aula_sync.py courses           print the enrolled courses and their folder mapping
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import html as htmllib
import json
import logging
import logging.handlers
import os
import pickle
import re
import shutil
import smtplib
import socket
import sys
import time
import traceback
import urllib.parse
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upf_login as L  # noqa: E402
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

HOME = os.path.expanduser("~")
DEST = os.path.join(HOME, "Library/Mobile Documents/com~apple~CloudDocs/Izobrazba/magisterij/materials")
APP_DIR = os.environ.get("AULA_SYNC_HOME", os.path.join(HOME, "Library/Application Support/aula-sync"))
STAGING = os.path.join(HOME, "Library/Caches/aula-sync")
LOG_DIR = os.path.join(HOME, "Library/Logs/aula-sync")
STATE = os.path.join(APP_DIR, "state.json")
COOKIES = os.path.join(APP_DIR, "cookies.pkl")
CONFIG = os.path.join(APP_DIR, "courses.json")
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "courses.default.json")

UPF_USER = os.environ.get("AULA_SYNC_UPF_USER", "U283341")
MAIL_TO = MAIL_FROM = "bozak.tomi@gmail.com"
SUFFIX = "_auto"
SPACING = 0.3            # seconds between requests
MAX_RUN_BYTES = 3 * 1024**3
MIN_FREE_BYTES = 5 * 1024**3
ERROR_MAIL_EVERY = 24 * 3600
NETWORK_MAIL_AFTER = 48 * 3600
SF_DATALESS = 0x40000000  # iCloud file evicted from local disk

SKIP_MODULES = {"forum", "url", "page", "quiz", "kalvidres", "kalvidassign", "hvp", "h5pactivity", "book",
                "lti", "choice", "feedback", "chat", "zoom", "bigbluebuttonbn", "subsection", "workshop", "glossary"}
VIDEO_EXT = {"mp4", "mov", "m4v", "webm", "mkv", "avi", "wmv", "flv", "mpeg", "mpg"}
CATEGORY_EXT = {
    "slides": {"ppt", "pptx", "pps", "ppsx", "key", "odp"},
    "readings": {"doc", "docx", "epub", "odt", "rtf", "djvu"},
    "code": {"ipynb", "py", "r", "rmd", "m", "jl", "c", "cpp", "h", "java", "js", "lp", "pl", "pddl", "sql", "sh",
             "zip", "tar", "gz", "tgz", "7z", "rar", "csv", "tsv", "json", "arff", "txt", "xml", "yaml", "yml",
             "parquet", "npy", "pkl", "mat", "comp", "data", "xlsx", "xls"},
}
EXERCISE_RE = re.compile(r"problem.?set|homework|\bhw\d|exercis|worksheet|practica|soluci|solution|quiz|exam|"
                         r"msc_dec|lab\d|project|assignment|enunciado", re.I)
READING_RE = re.compile(r"paper|reading|article|chapter|book|lectura|survey|arxiv|\d{4}\.\d{4,5}|pnas|"
                        r"et.?al|proceedings|journal|_(19|20)\d\d\b|(19|20)\d\d\.pdf$", re.I)
SLIDE_RE = re.compile(r"slide|lecture|theory|tema|class|session|^l\d|^s\d\d|week|unit|intro", re.I)

log = logging.getLogger("aula-sync")


# ---------------------------------------------------------------- utilities
def setup_logging(verbose):
    os.makedirs(LOG_DIR, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "aula-sync.log"), maxBytes=1_000_000,
                                             backupCount=5)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    if verbose:
        log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)
    err = os.path.join(LOG_DIR, "launchd.err")
    if os.path.exists(err) and os.path.getsize(err) > 1_000_000:
        open(err, "w").close()


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def clean_name(s):
    s = htmllib.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s)
    return re.sub(r"\s+", " ", s)[:120].strip(" .") or "untitled"


def auto_name(filename):
    """'L1.pdf' -> 'L1_auto.pdf'; 'archive.tar.gz' -> 'archive_auto.tar.gz'."""
    m = re.match(r"^(.*?)(\.tar\.gz|\.[A-Za-z0-9]{1,8})?$", filename)
    stem, ext = m.group(1), m.group(2) or ""
    if not stem:
        stem, ext = filename, ""
    return f"{stem}{SUFFIX}{ext}"


def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def categorize(filename, module, context=""):
    """Return the category folder key for a file."""
    if module == "assign":
        return "assignments"
    e = ext_of(filename)
    for cat, exts in CATEGORY_EXT.items():
        if e in exts:
            return cat
    if e == "pdf":
        name = f"{filename} {context}"
        if EXERCISE_RE.search(name):
            return "exercises"
        if SLIDE_RE.search(filename):
            return "slides"
        if READING_RE.search(name) or len(re.findall(r"[A-Za-z]{2,}", filename[:-4])) >= 5:
            return "readings"  # paper-like: keywords or a long title such as Building_machines_that_learn_...
        return "slides"
    return "other"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_dataless(st):
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


class CourseIndex:
    """Sizes -> paths of the user's own (non-_auto) files in a course folder, for dedupe."""

    def __init__(self, root):
        self.by_size = {}
        self._hash = {}
        if not os.path.isdir(root):
            return
        for dp, dns, fns in os.walk(root):
            for fn in fns:
                if fn.startswith(".") or SUFFIX + "." in fn or fn.endswith(SUFFIX):
                    continue
                p = os.path.join(dp, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if not is_dataless(st):
                    self.by_size.setdefault(st.st_size, []).append(p)

    def find_identical(self, size, digest):
        for p in self.by_size.get(size, []):
            if p not in self._hash:
                try:
                    self._hash[p] = sha256(p)
                except OSError:
                    self._hash[p] = None
            if self._hash[p] == digest:
                return p
        return None


# ---------------------------------------------------------------- moodle client
class Moodle:
    def __init__(self):
        self.s = L.new_session()
        if os.path.exists(COOKIES):
            try:
                with open(COOKIES, "rb") as f:
                    self.s.cookies.update(pickle.load(f))
            except Exception:  # corrupt jar -> fresh login
                pass
        self.key = None

    def login(self):
        user, pw = L.keychain("aula-sync-upf", UPF_USER)
        try:
            _, totp = L.keychain("aula-sync-totp", UPF_USER)
        except L.AuthError:
            totp = None
        html = L.login(self.s, user, pw, totp)
        self.key = L.sesskey(html)
        old = os.umask(0o077)
        try:
            with open(COOKIES, "wb") as f:
                pickle.dump(self.s.cookies, f)
        finally:
            os.umask(old)

    def get(self, url, **kw):
        time.sleep(SPACING)
        r = self.s.get(url, timeout=kw.pop("timeout", 90), **kw)
        if "/login/index.php" in r.url or "autenticacio.upf.edu" in r.url:
            raise L.AuthError(f"Session lost while fetching {url}")
        return r

    def ajax(self, method, args):
        time.sleep(SPACING)
        r = self.s.post(f"{L.BASE}/lib/ajax/service.php?sesskey={self.key}&info={method}",
                        json=[{"index": 0, "methodname": method, "args": args}], timeout=90)
        res = r.json()
        res = res[0] if isinstance(res, list) else res
        if res.get("error"):
            exc = res.get("exception") or {}
            raise RuntimeError(f"{method}: {exc.get('errorcode')} {exc.get('message')}")
        data = res["data"]
        return json.loads(data) if isinstance(data, str) else data

    def courses(self):
        d = self.ajax("core_course_get_enrolled_courses_by_timeline_classification",
                      {"offset": 0, "limit": 0, "classification": "all", "sort": "fullname"})
        return d["courses"]

    def course_state(self, cid):
        return self.ajax("core_courseformat_get_state", {"courseid": cid})


PF_RE = re.compile(r'https://aulaglobal\.upf\.edu/pluginfile\.php/[^"\'\s<>]+')


def pluginfile_name(url):
    path = urllib.parse.urlparse(url).path
    return urllib.parse.unquote(path.rsplit("/", 1)[-1])


def strip_query(url):
    return url.split("?", 1)[0]


# ---------------------------------------------------------------- discovery
def discover(m, course, ccfg):
    """Yield items: dict(key, url, filename, module, category, subdir, kind)."""
    state = m.course_state(course["id"])
    sections = {s["id"]: clean_name(s.get("title")) for s in state["section"]}
    for cm in state["cm"]:
        mod = cm["module"]
        if mod in SKIP_MODULES or not cm.get("uservisible", True) or mod == "label":
            continue
        name = clean_name(cm.get("name"))
        section = sections.get(cm.get("sectionid"), "")
        if mod == "resource":
            yield dict(key=f"cm{cm['id']}", url=f"{L.BASE}/mod/resource/view.php?id={cm['id']}&redirect=1",
                       module=mod, context=f"{name} {section}", subdir="", kind="resource")
        elif mod == "folder":
            page = m.get(cm["url"]).text
            soup = BeautifulSoup(page, "html.parser")
            region = soup.find(id="region-main") or soup
            for a in region.find_all("a", href=PF_RE):
                u = strip_query(a["href"])
                if "/mod_folder/content/" not in u:
                    continue
                # .../mod_folder/content/<rev>/<sub/path>/<file>
                rel = urllib.parse.unquote(u.split("/mod_folder/content/", 1)[1].split("/", 1)[1])
                sub = os.path.dirname(rel)
                yield dict(key=f"cm{cm['id']}:{rel}", url=u, module=mod, context=f"{name} {section}",
                           subdir=os.path.join(clean_name(name), *[clean_name(p) for p in sub.split("/") if p]),
                           filename=os.path.basename(rel), kind="file")
        elif mod == "assign":
            yield from discover_assign(m, cm, name)
        else:
            log.info("skip unknown module %s (%s) in %s", mod, name, course["shortname"])
    # files embedded in labels / section summaries (not blocks, not user icons)
    page = m.get(f"{L.BASE}/course/view.php?id={course['id']}").text
    for u in sorted(set(PF_RE.findall(page))):
        u = strip_query(htmllib.unescape(u))
        if not re.search(r"/(mod_label/intro|course/section)/", u):
            continue
        fn = pluginfile_name(u)
        if ext_of(fn) in VIDEO_EXT:
            continue
        yield dict(key=f"emb:{u.split('/pluginfile.php/', 1)[1]}", url=u, module="label", context="",
                   subdir="", filename=fn, kind="file")


def discover_assign(m, cm, name):
    page = m.get(cm["url"]).text
    soup = BeautifulSoup(page, "html.parser")
    main = soup.find(id="region-main") or soup
    adir = clean_name(name)
    base = dict(module="assign", context=name)
    # brief: title + dates + description (+ intro attachments)
    parts = [f"<h1>{htmllib.escape(name)}</h1>"]
    dates = main.select_one(".activity-dates")
    if dates:
        parts.append(str(dates))
    intro = main.select_one("#intro")
    if intro:
        parts.append(str(intro))
    yield dict(base, key=f"cm{cm['id']}:brief", kind="html", filename="brief.html", subdir=adir,
               html=html_doc(name, "".join(parts)), source=cm["url"])
    seen = set()
    for a in main.find_all("a", href=PF_RE):
        u = strip_query(a["href"])
        if u in seen:
            continue
        seen.add(u)
        if "/mod_assign/introattachment/" in u or "/mod_assign/intro/" in u:
            sub = adir
        elif "/assignsubmission_file/" in u:
            sub = os.path.join(adir, "submission")
        elif "/assignfeedback_" in u:
            sub = os.path.join(adir, "feedback")
        else:
            continue
        yield dict(base, key=f"cm{cm['id']}:{u.split('/pluginfile.php/', 1)[1]}", url=u, kind="file",
                   filename=pluginfile_name(u), subdir=sub)
    # feedback text / grade
    fb = main.select_one(".feedback") or next(
        (h.find_parent("div") for h in main.find_all(["h2", "h3"]) if h.get_text(strip=True) == "Feedback"), None)
    if fb is not None and fb.get_text(strip=True):
        yield dict(base, key=f"cm{cm['id']}:feedback", kind="html", filename="feedback.html", subdir=adir,
                   html=html_doc(f"{name} - feedback", str(fb)), source=cm["url"])


def html_doc(title, body):
    return (f'<!doctype html><meta charset="utf-8"><title>{htmllib.escape(title)}</title>'
            '<style>body{font:16px -apple-system,sans-serif;max-width:46em;margin:2em auto;padding:0 1em}</style>'
            f"{body}")


# ---------------------------------------------------------------- sync
class Disk:
    def __init__(self):
        self.planned = 0


def target_path(item, cfolder, ccfg, filename):
    cat = categorize(filename, item["module"], item.get("context", ""))
    sub = ccfg.get("subfolders", {}).get(cat, cat)
    parts = [DEST, cfolder, sub]
    if item.get("subdir"):
        parts.append(item["subdir"])
    return os.path.join(*parts, auto_name(filename))


def place(tmp, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(tmp, dst)


def safe_dst(dst, rec):
    """Never clobber a file we don't own unmodified.

    `dst` may be overwritten only if it is the path recorded for this very item AND still
    byte-identical to what we wrote (so iPad annotations / edits survive a teacher's update).
    Otherwise pick a free sibling name: 'L3_auto (2).pdf'.
    """
    if not os.path.lexists(dst):
        return dst
    if rec and rec.get("path") == os.path.relpath(dst, DEST) and rec.get("sha256"):
        try:
            if sha256(dst) == rec["sha256"]:
                return dst
        except OSError:
            pass
    stem, ext = re.match(r"^(.*?)(\.tar\.gz|\.[A-Za-z0-9]{1,8})?$", os.path.basename(dst)).groups()
    for i in range(2, 1000):
        cand = os.path.join(os.path.dirname(dst), f"{stem} ({i}){ext or ''}")
        if not os.path.lexists(cand):
            return cand
    raise RuntimeError(f"no free name for {dst}")


def sync_item(m, item, cfolder, ccfg, state, index, dry, disk, changes):
    key = f"{ccfg['id']}:{item['key']}"
    rec = state["files"].get(key)
    if item["kind"] == "html":
        body = item["html"].encode()
        digest = hashlib.sha256(re.sub(rb"\s+", b" ", body)).hexdigest()
        dst = target_path(item, cfolder, ccfg, item["filename"])
        if rec and rec.get("version") == digest:
            return
        if dry:
            changes.append(("new" if not rec else "updated", dst, len(body)))
            return
        tmp = os.path.join(STAGING, "page.part")
        with open(tmp, "wb") as f:
            f.write(body)
        if rec and rec.get("path"):
            dst = os.path.join(DEST, rec["path"])
        dst = safe_dst(dst, rec)
        place(tmp, dst)
        state["files"][key] = dict(version=digest, path=os.path.relpath(dst, DEST), size=len(body),
                                   sha256=hashlib.sha256(body).hexdigest(), time=time.time())
        changes.append(("new" if not rec else "updated", dst, len(body)))
        return

    r = m.get(item["url"], stream=True)
    try:
        if r.status_code != 200:
            log.warning("HTTP %s for %s", r.status_code, item["url"])
            return
        final = strip_query(r.url)
        if "pluginfile.php" not in final:  # e.g. resource that shows an embed page instead of redirecting
            soup = BeautifulSoup(r.text, "html.parser")
            link = (soup.find(id="region-main") or soup).find("a", href=PF_RE)
            if not link:
                log.info("no file behind %s", item["url"])
                return
            r.close()
            r = m.get(strip_query(link["href"]), stream=True)
            final = strip_query(r.url)
        filename = item.get("filename") or pluginfile_name(final)
        if ext_of(filename) in VIDEO_EXT:
            return
        size = int(r.headers.get("Content-Length") or -1)
        version = f"{final}|{size}|{r.headers.get('Last-Modified', '')}"
        if rec and rec.get("version") == version:
            return  # unchanged (also when the user deleted/moved our copy: respect that)
        if rec and rec.get("url") == final and rec.get("size") == size and size >= 0:
            rec["version"] = version  # only Last-Modified moved; content same revision
            return
        dst = target_path(item, cfolder, ccfg, filename)
        status = "new" if not rec else "updated"
        disk.planned += max(size, 0)
        if disk.planned > MAX_RUN_BYTES:
            raise DiskGuard(f"run would download more than {MAX_RUN_BYTES >> 30} GB")
        if shutil.disk_usage(DEST).free - max(size, 0) < MIN_FREE_BYTES:
            raise DiskGuard("less than 5 GB would remain free on the Mac")
        if dry:
            changes.append((status, dst, size))
            return
        tmp = os.path.join(STAGING, "download.part")
        h = hashlib.sha256()
        n = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
        compressed = r.headers.get("Content-Encoding", "identity") != "identity"  # Content-Length = wire size
        if size >= 0 and n != size and not compressed:
            os.remove(tmp)
            raise IOError(f"truncated download {final} ({n}/{size} bytes)")
        digest = h.hexdigest()
        newrec = dict(version=version, url=final, size=n, sha256=digest, time=time.time())
        if status == "new":
            twin = index.find_identical(n, digest)
            if twin:
                os.remove(tmp)
                newrec.update(path=None, duplicate_of=os.path.relpath(twin, DEST))
                state["files"][key] = newrec
                log.info("already have %s as %s", filename, twin)
                return
        elif rec.get("sha256") == digest:
            os.remove(tmp)
            state["files"][key] = dict(rec, **{k: newrec[k] for k in ("version", "url", "size")})
            return
        if status == "updated" and rec.get("duplicate_of") is None and rec.get("path"):
            dst = os.path.join(DEST, rec["path"])  # keep the location chosen the first time
        dst = safe_dst(dst, rec)
        place(tmp, dst)
        newrec["path"] = os.path.relpath(dst, DEST)
        state["files"][key] = newrec
        changes.append((status, dst, n))
        log.info("%s %s (%d bytes)", status, dst, n)
    finally:
        r.close()


class DiskGuard(Exception):
    pass


def course_config(config, course):
    cid = str(course["id"])
    if cid not in config["courses"]:
        folder = re.sub(r"[^a-z0-9]+", "_", re.sub(r"\(.*?\)|\d{4}-[\w.-]+", "", course["fullname"]).lower()).strip("_")
        config["courses"][cid] = {"name": clean_name(course["fullname"]), "folder": folder or cid, "include": True}
        config["_dirty"] = True
        log.info("new course %s -> %s", course["fullname"], folder)
    c = dict(config["courses"][cid])
    c["id"] = cid
    return c


def run(dry=False):
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(STAGING, exist_ok=True)
    lock = open(os.path.join(APP_DIR, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("another run is active; exiting")
        return
    state = load_json(STATE, {"files": {}, "mail": {}})
    state.setdefault("mail", {})
    try:
        wait_for_network()
        if not os.path.isdir(DEST):
            raise RuntimeError(f"destination folder missing: {DEST}")
        config = load_json(CONFIG, None) or load_json(DEFAULT_CONFIG, {"courses": {}})
        m = Moodle()
        m.login()
        changes, disk = {}, Disk()
        for course in m.courses():
            ccfg = course_config(config, course)
            if not ccfg.get("include", True):
                continue
            index = CourseIndex(os.path.join(DEST, ccfg["folder"]))
            cl = changes.setdefault(ccfg["name"], [])
            for item in discover(m, course, ccfg):
                try:
                    sync_item(m, item, ccfg["folder"], ccfg, state, index, dry, disk, cl)
                except (DiskGuard, L.AuthError):
                    raise
                except Exception as e:  # one bad file must not stop the run
                    log.warning("item %s failed: %s", item.get("key"), e)
                    state.setdefault("item_errors", {})[f"{ccfg['id']}:{item['key']}"] = str(e)[:300]
            if not dry:
                save_json(STATE, state)
        if config.pop("_dirty", False) and not dry:
            save_json(CONFIG, config)
        changes = {k: v for k, v in changes.items() if v}
        total = sum(c[2] for v in changes.values() for c in v if c[2] > 0)
        if dry:
            print_dry(changes, total)
        else:
            state["last_success"] = time.time()
            log.info("run ok: %d changed files, %.1f MB", sum(map(len, changes.values())), total / 1e6)
            pending = state.setdefault("pending_mail", {})
            for course, items in changes.items():
                pending.setdefault(course, []).extend([s, os.path.relpath(p, DEST), n] for s, p, n in items)
            save_json(STATE, state)
            if pending:
                try:
                    send_mail(f"Aula Global: {sum(map(len, pending.values()))} new/updated files",
                              changes_text({c: [(s, os.path.join(DEST, p), n) for s, p, n in v]
                                            for c, v in pending.items()}))
                    state["pending_mail"] = {}
                except Exception as e:  # keep the list; it goes out with the next successful mail
                    log.error("change mail not sent (kept for next run): %s", e)
    except L.AuthError as e:
        error_mail(state, "auth", f"Aula Global login failed: {e}\n\n" + REAUTH_HELP)
    except DiskGuard as e:
        error_mail(state, "disk", f"Aula sync stopped by the disk guard: {e}")
    except (socket.gaierror, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.warning("network problem: %s", e)
        if time.time() - state.get("last_success", time.time()) > NETWORK_MAIL_AFTER:
            error_mail(state, "network", f"Aula sync has not succeeded for 48 h (network): {e}")
    except Exception:
        error_mail(state, "crash", traceback.format_exc())
    finally:
        if not dry:
            save_json(STATE, state)
        lock.close()


REAUTH_HELP = """To fix: the sync logs in with the UPF password + TOTP secret stored in the macOS Keychain
(items aula-sync-upf and aula-sync-totp, account U283341). If you changed your UPF password or
re-enrolled 2FA, re-export Apple Passwords and run tools/import_from_apple_passwords.py (see README)."""


def wait_for_network(limit=180):
    t0 = time.time()
    while True:
        try:
            socket.getaddrinfo("aulaglobal.upf.edu", 443)
            return
        except socket.gaierror:
            if time.time() - t0 > limit:
                raise
            time.sleep(15)


def print_dry(changes, total):
    for course, items in changes.items():
        print(f"\n{course}")
        for status, path, size in items:
            print(f"  {status:7} {os.path.relpath(path, DEST)}  {size / 1e6:.2f} MB" if size >= 0 else
                  f"  {status:7} {os.path.relpath(path, DEST)}  ? MB")
    print(f"\nTOTAL to download: {total / 1e6:.1f} MB in {sum(map(len, changes.values()))} files")


def changes_text(changes):
    lines = []
    for course, items in changes.items():
        lines.append(course)
        for status, path, size in items:
            lines.append(f"  [{status}] {os.path.relpath(path, DEST)}")
        lines.append("")
    lines.append(f"Folder: {DEST}")
    return "\n".join(lines)


# ---------------------------------------------------------------- mail
def send_mail(subject, body):
    _, pw = L.keychain("aula-sync-gmail", MAIL_FROM)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Aula sync <{MAIL_FROM}>", MAIL_TO
    msg.set_content(body)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
        s.starttls()
        s.login(MAIL_FROM, pw)
        s.send_message(msg)
    log.info("mail sent: %s", subject)


def error_mail(state, kind, text):
    log.error("%s: %s", kind, text)
    last = state["mail"].get(kind, 0)
    if time.time() - last < ERROR_MAIL_EVERY:
        return
    try:
        send_mail(f"Aula sync problem: {kind}", text)
        state["mail"][kind] = time.time()
    except Exception as e:
        log.error("could not send error mail: %s", e)


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "test-email", "courses"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    setup_logging(a.verbose or a.cmd != "run" or a.dry_run)
    if a.cmd == "run":
        run(dry=a.dry_run)
    elif a.cmd == "test-email":
        send_mail("Aula sync: test email", f"Test email from aula-sync at {dt.datetime.now():%Y-%m-%d %H:%M}.\n"
                  f"Destination: {DEST}")
        print("sent")
    elif a.cmd == "courses":
        config = load_json(CONFIG, None) or load_json(DEFAULT_CONFIG, {"courses": {}})
        m = Moodle()
        m.login()
        for c in m.courses():
            cc = course_config(config, c)
            print(f"{c['id']:>6}  {'on ' if cc.get('include', True) else 'OFF'}  {cc['folder']:<36} {c['fullname']}")


if __name__ == "__main__":
    main()
