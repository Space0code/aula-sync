#!/usr/bin/python3
"""Copy the UPF SSO password + TOTP secret from an Apple Passwords CSV export into
the login Keychain, then delete the CSV. Nothing secret is printed.

Usage: /usr/bin/python3 tools/import_from_apple_passwords.py ~/Downloads/Passwords.csv [U283341]
"""
import csv
import os
import subprocess
import sys
import urllib.parse

HOST = "autenticacio.upf.edu"


def store(service, account, secret):
    subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", service,
                    "-a", account, "-w", secret], check=True)


def main():
    path = os.path.expanduser(sys.argv[1])
    user = sys.argv[2] if len(sys.argv) > 2 else "U283341"
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f)
                    if HOST in (r.get("URL") or "") and (r.get("Username") or "").lower() == user.lower()]
        if not rows:
            sys.exit(f"No entry for {user} @ {HOST} in the export")
        pw = next((r["Password"] for r in rows if r.get("Password")), "")
        otp = next((r["OTPAuth"] for r in rows if r.get("OTPAuth")), "")
        if not pw:
            sys.exit("Entry found, but it has no password")
        store("aula-sync-upf", user, pw)
        print(f"stored aula-sync-upf / {user} ({len(pw)} chars)")
        if otp:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(otp).query)
            secret = q["secret"][0]
            if q.get("digits", ["6"])[0] != "6" or q.get("period", ["30"])[0] != "30" \
                    or q.get("algorithm", ["SHA1"])[0].upper() != "SHA1":
                print("note: non-default TOTP parameters:", {k: v[0] for k, v in q.items() if k != "secret"})
            store("aula-sync-totp", user, secret)
            print(f"stored aula-sync-totp / {user}")
        else:
            print("WARNING: entry has no OTPAuth column/value - TOTP secret not stored")
    finally:
        if os.path.exists(path):
            os.remove(path)
            print(f"deleted {path} (also empty the Trash if you moved a copy there)")


if __name__ == "__main__":
    main()
