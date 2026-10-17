"""UPF Aula Global login: Moodle -> adAS SAML IdP -> Moodle session."""
import os
import re
import subprocess
import warnings

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE = "https://aulaglobal.upf.edu"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


class AuthError(Exception):
    """Login failed in a way that needs a human (bad password, OTP, changed form)."""


def keychain(service, account=None):
    """Return (account, secret) of a generic-password item in the login keychain."""
    cmd = ["/usr/bin/security", "find-generic-password", "-s", service]
    if account:
        cmd += ["-a", account]
    meta = subprocess.run(cmd, capture_output=True, text=True)
    if meta.returncode != 0:
        raise AuthError(f"Keychain item '{service}' not found")
    m = re.search(r'"acct"<blob>="([^"]*)"', meta.stdout)
    acct = m.group(1) if m else account
    secret = subprocess.run(cmd + ["-w"], capture_output=True, text=True, check=True).stdout.rstrip("\n")
    return acct, secret


def _fields(form):
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and inp.get("type", "text") not in ("submit", "button", "image"):
            data[name] = inp.get("value", "")
    return data


def _post_saml_response(sess, resp):
    """Follow the IdP's auto-submit form(s) carrying SAMLResponse back to Moodle."""
    for _ in range(3):
        if "SAMLResponse" not in resp.text:
            return resp
        soup = BeautifulSoup(resp.text, "html.parser")
        form = next(f for f in soup.find_all("form") if f.find("input", attrs={"name": "SAMLResponse"}))
        resp = sess.post(requests.compat.urljoin(resp.url, form.get("action")), data=_fields(form), timeout=60)
    return resp


def is_logged_in(html):
    return '"sesskey":"' in html and "logout.php" in html


def sesskey(html):
    m = re.search(r'"sesskey":"([^"]+)"', html)
    return m.group(1) if m else None


def _dump(debug_dir, name, text):
    if debug_dir:
        with open(os.path.join(debug_dir, name), "w") as f:
            f.write(text)


def login(sess, username, password, totp_secret=None, debug_dir=None):
    """Run the SAML login on `sess`. Returns the HTML of a logged-in Moodle page."""
    resp = sess.get(f"{BASE}/my/", timeout=60)
    if is_logged_in(resp.text):
        return resp.text
    resp = sess.get(f"{BASE}/login/index.php", timeout=60)
    soup = BeautifulSoup(resp.text, "html.parser")
    user_input = soup.find("input", attrs={"name": "adAS_username"})
    if user_input is None:  # IdP session still valid -> straight SAMLResponse
        resp = _post_saml_response(sess, resp)
        if is_logged_in(resp.text):
            return resp.text
        _dump(debug_dir, "unexpected_login.html", resp.text)
        raise AuthError(f"Unexpected login page at {resp.url}")
    form = user_input.find_parent("form")
    data = _fields(form)
    data.update(adAS_username=username, adAS_password=password, adAS_submit="Aceptar")
    resp = sess.post(requests.compat.urljoin(resp.url, form.get("action")), data=data, timeout=60,
                     headers={"Origin": "https://autenticacio.upf.edu", "Referer": resp.url})
    _dump(debug_dir, "after_password.html", resp.text)

    verify = BeautifulSoup(resp.text, "html.parser").find("a", class_="notification_2Factor_button")
    if verify is not None and "SAMLResponse" not in resp.text:
        if not totp_secret:
            raise AuthError("UPF SSO asks for a 2FA code and no TOTP secret is configured")
        resp = sess.post(requests.compat.urljoin(resp.url, verify.get("href")), timeout=60,
                         data={"adAS_authn_module": "otp_module", "adAS_mode": "authn",
                               "adAS_otp_code": totp_now(totp_secret)},
                         headers={"Origin": "https://autenticacio.upf.edu", "Referer": resp.url})
        _dump(debug_dir, "after_otp.html", resp.text)
        if "SAMLResponse" not in resp.text and "notification_2Factor_button" in resp.text:
            raise AuthError("UPF SSO rejected the 2FA code (TOTP secret wrong or clock skew?)")

    if "SAMLResponse" not in resp.text and \
            BeautifulSoup(resp.text, "html.parser").find("input", attrs={"name": "adAS_password"}):
        raise AuthError("UPF SSO rejected the username/password")
    resp = _post_saml_response(sess, resp)
    if not is_logged_in(resp.text):
        resp = sess.get(f"{BASE}/my/", timeout=60)
    if not is_logged_in(resp.text):
        _dump(debug_dir, "final.html", resp.text)
        raise AuthError(f"Login did not produce a Moodle session (ended at {resp.url})")
    return resp.text


def totp_now(secret):
    """Current TOTP code; waits out the last 3 s of a period so the code can't expire in flight."""
    import time
    import pyotp
    if 30 - time.time() % 30 < 3:
        time.sleep(4)
    return pyotp.TOTP(secret).now()


def new_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ca,es;q=0.9,en;q=0.8",
                      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    return s


if __name__ == "__main__":  # login probe: python upf_login.py U123456 [debug_dir]
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: upf_login.py <upf_user> [debug_dir]")
    dbg = sys.argv[2] if len(sys.argv) > 2 else None
    user, pw = keychain("aula-sync-upf", sys.argv[1])
    _, totp = keychain("aula-sync-totp", user)
    s = new_session()
    try:
        html = login(s, user, pw, totp, debug_dir=dbg)
        print("LOGIN OK, sesskey present:", bool(sesskey(html)))
    except AuthError as e:
        print("AUTH ERROR:", e)
