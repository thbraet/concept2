#!/usr/bin/env python3
"""
Fetch all Concept2 rowing workouts via the Logbook API (OAuth2).

Usage:
  1. Create an app at https://log.concept2.com/developer
     - Set redirect URI to: http://localhost:8765/callback
     - Tick scopes: user:read, results:read
  2. Fill in your client_id and client_secret in the .env file next to this script.
  3. Run:  python3 fetch_workouts.py
  4. A browser window will open for you to log in and authorize.
  5. All workouts are saved to workouts.json when done.
"""

import os
import ssl
import json
import time
import threading
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


def _load_env(path: Path = Path(__file__).parent / ".env"):
    """Load key=value pairs from a .env file into os.environ (if not already set)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

_load_env()


# ── HTTP session ─────────────────────────────────────────────────────────────
# Behind the corporate TLS proxy the CA chain validates fine, but its certs
# lack an Authority Key Identifier extension, which Python 3.14's OpenSSL
# rejects under VERIFY_X509_STRICT (on by default). We keep verification on
# against the corporate CA bundle but clear that one strict flag.
class _NonStrictAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if ca_bundle and Path(ca_bundle).exists():
            ctx.load_verify_locations(ca_bundle)
        else:
            ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _NonStrictAdapter())
    return session


HTTP = _make_session()


# ── Configuration ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ.get("C2_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("C2_CLIENT_SECRET", "")
REDIRECT_URI  = "http://localhost:8765/callback"
SCOPES        = "user:read,results:read"

BASE_URL      = "https://log.concept2.com"
API_BASE      = f"{BASE_URL}/api"
TOKEN_FILE    = Path("tokens.json")
OUTPUT_FILE   = Path("workouts.json")
STROKES_FILE  = Path("strokes.json")
PROFILE_FILE  = Path("profile.json")
# ───────────────────────────────────────────────────────────────────────────────


# ── OAuth helpers ──────────────────────────────────────────────────────────────
_auth_code = None  # type: str | None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            body = b"<h2>Authorization successful! You can close this tab.</h2>"
            self.send_response(200)
        else:
            body = b"<h2>Authorization failed. No code received.</h2>"
            self.send_response(400)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def _get_auth_code() -> str:
    """Open browser for OAuth and wait for redirect with code."""
    # Build URL manually so colons in scope names are not percent-encoded
    auth_url = (
        f"{BASE_URL}/oauth/authorize"
        f"?client_id={urllib.parse.quote(CLIENT_ID, safe='')}"
        f"&scope={urllib.parse.quote(SCOPES, safe=':,')}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    )

    server = HTTPServer(("localhost", 8765), _CallbackHandler)
    t = threading.Thread(target=server.handle_request)
    t.daemon = True
    t.start()

    print(f"\nOpening browser for authorization...\nURL: {auth_url}\n")
    webbrowser.open(auth_url)

    t.join(timeout=120)
    server.server_close()

    if _auth_code is None:
        raise RuntimeError("Did not receive authorization code within 120s.")
    return _auth_code


def _exchange_code(code: str) -> dict:
    resp = HTTP.post(f"{BASE_URL}/oauth/access_token", data={
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    })
    resp.raise_for_status()
    return resp.json()


def _refresh_token(refresh: str) -> dict:
    resp = HTTP.post(f"{BASE_URL}/oauth/access_token", data={
        "grant_type":    "refresh_token",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh,
    })
    resp.raise_for_status()
    return resp.json()


def get_tokens() -> dict:
    """Return a valid token dict, refreshing or re-authorizing as needed."""
    if TOKEN_FILE.exists():
        tokens = json.loads(TOKEN_FILE.read_text())
        # Try refresh
        try:
            print("Refreshing existing access token...")
            tokens = _refresh_token(tokens["refresh_token"])
            TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
            return tokens
        except Exception as e:
            print(f"Refresh failed ({e}), re-authorizing...")

    code   = _get_auth_code()
    tokens = _exchange_code(code)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    print("Tokens saved to tokens.json")
    return tokens
# ───────────────────────────────────────────────────────────────────────────────


# ── API helpers ────────────────────────────────────────────────────────────────
def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/vnd.c2logbook.v1+json",
    }


def get_profile(token: str) -> dict:
    resp = HTTP.get(f"{API_BASE}/users/me", headers=_headers(token))
    resp.raise_for_status()
    return resp.json()["data"]


def get_user_id(token: str) -> int:
    return get_profile(token)["id"]


def fetch_all_workouts(token: str, user_id: int):
    """Fetch every result page for the user (max 100 per page)."""
    workouts = []
    page = 1
    per_page = 100

    while True:
        resp = HTTP.get(
            f"{API_BASE}/users/{user_id}/results",
            headers=_headers(token),
            params={"page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("data", [])
        workouts.extend(batch)

        pagination = data.get("meta", {}).get("pagination", {})
        total_pages = pagination.get("total_pages", 1)
        total       = pagination.get("total", len(workouts))

        print(f"  Page {page}/{total_pages} — {len(workouts)}/{total} workouts fetched")

        if page >= total_pages:
            break
        page += 1
        time.sleep(0.25)  # be polite to the API

    return workouts


def fetch_strokes(token: str, user_id: int, result_id: int):
    """Return the per-stroke samples for one result, or None if unavailable.

    Each sample is {t, d, p, spm, hr}: elapsed time (tenths of a second),
    cumulative distance (tenths of a metre), instantaneous pace (tenths of a
    second per 500 m), stroke rate (spm) and heart rate (bpm).
    """
    resp = HTTP.get(
        f"{API_BASE}/users/{user_id}/results/{result_id}/strokes",
        headers=_headers(token),
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("data", [])


def fetch_all_strokes(token: str, user_id: int, workouts: list):
    """Fetch stroke data for every workout that has it, stored columnar by id.

    Columnar (parallel arrays of ints) keeps the embedded JSON compact —
    ~50k strokes compress to well under a megabyte this way.
    """
    ids = [w["id"] for w in workouts if w.get("stroke_data")]
    strokes = {}
    for i, rid in enumerate(ids, 1):
        samples = fetch_strokes(token, user_id, rid)
        if samples:
            strokes[str(rid)] = {
                "t":   [s.get("t")   for s in samples],
                "d":   [s.get("d")   for s in samples],
                "p":   [s.get("p")   for s in samples],
                "spm": [s.get("spm") for s in samples],
                "hr":  [s.get("hr")  for s in samples],
            }
        if i % 20 == 0 or i == len(ids):
            print(f"  {i}/{len(ids)} workouts' strokes fetched")
        time.sleep(0.05)  # be polite to the API
    return strokes
# ───────────────────────────────────────────────────────────────────────────────


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print(
            "ERROR: CLIENT_ID and CLIENT_SECRET are not set.\n\n"
            "Steps to get them:\n"
            "  1. Go to https://log.concept2.com/developer\n"
            "  2. Create a new application\n"
            "  3. Set redirect URI to: http://localhost:8765/callback\n"
            "  4. Copy your client_id and client_secret, then run:\n\n"
            "     C2_CLIENT_ID=xxx C2_CLIENT_SECRET=yyy python3 fetch_workouts.py\n"
        )
        return

    tokens  = get_tokens()
    token   = tokens["access_token"]

    print("Fetching user info...")
    profile = get_profile(token)
    user_id = profile["id"]
    print(f"User ID: {user_id}")

    # Persist the profile fields the dashboard derives metrics from.
    # weight is stored in hundredths of a kilogram (e.g. 9000 -> 90.00 kg).
    PROFILE_FILE.write_text(json.dumps({
        "id":              profile.get("id"),
        "gender":          profile.get("gender"),
        "dob":             profile.get("dob"),
        "weight_kg":       (profile.get("weight") or 0) / 100 or None,
        "max_heart_rate":  profile.get("max_heart_rate"),
    }, indent=2))

    print("\nFetching all workouts...")
    workouts = fetch_all_workouts(token, user_id)

    OUTPUT_FILE.write_text(json.dumps(workouts, indent=2))
    print(f"\nDone! {len(workouts)} workouts saved to {OUTPUT_FILE}")

    print("\nFetching per-stroke data...")
    strokes = fetch_all_strokes(token, user_id, workouts)
    STROKES_FILE.write_text(json.dumps(strokes))
    print(f"Stroke data for {len(strokes)} workouts saved to {STROKES_FILE}")


if __name__ == "__main__":
    main()
