#!/usr/bin/env python3
"""
shutterstock-auth-setup.py — One-time OAuth2 authorization for contributor uploads.

Run this ONCE on any machine that can reach the NAS (192.168.100.202) in a browser.
A local server on port 8754 captures the OAuth callback automatically — no URL pasting.

Before running, register this redirect URI in the Shutterstock app:
  http://192.168.100.202:8754/callback
  (shutterstock.com/account/developers/apps → your app → Callback URL)

Usage:
  python3 shutterstock-auth-setup.py

Saves SHUTTERSTOCK_REFRESH_TOKEN to .env when done.
"""

import http.server, json, secrets, sys, threading, urllib.error, urllib.request, urllib.parse, webbrowser
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
ENV_FILE     = SCRIPT_DIR / ".env"
SS_AUTH_URL  = "https://www.shutterstock.com/oauth/authorize"
SS_TOKEN_URL = "https://api.shutterstock.com/v2/oauth/access_token"
CALLBACK_PORT = 8754
REDIRECT_URI  = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPES        = "user.view contributors.list collections.edit.add"


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def update_env(path, key, value):
    lines = path.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def main():
    cfg = load_env(ENV_FILE)
    client_id     = cfg.get("SHUTTERSTOCK_CLIENT_ID", "")
    client_secret = cfg.get("SHUTTERSTOCK_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("ERROR: Set SHUTTERSTOCK_CLIENT_ID and SHUTTERSTOCK_CLIENT_SECRET in .env first.")
        sys.exit(1)

    state    = secrets.token_urlsafe(16)
    captured = {}  # shared between server thread and main thread

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # type: ignore[override]
            pass  # silence access log

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            captured["code"]  = (qs.get("code")  or [""])[0]
            captured["state"] = (qs.get("state") or [""])[0]
            captured["error"] = (qs.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if captured["code"]:
                self.wfile.write(b"<h2>Authorization successful! You can close this tab.</h2>")
            else:
                err = captured["error"].encode()
                self.wfile.write(b"<h2>Authorization failed: " + err + b"</h2>")
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = http.server.HTTPServer(("0.0.0.0", CALLBACK_PORT), CallbackHandler)

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"{SS_AUTH_URL}?{params}"

    print("Redirect URI to register in Shutterstock portal:")
    print(f"  {REDIRECT_URI}")
    print()
    print("Two ways to run this:")
    print("  A) SSH tunnel: ssh -L 8754:localhost:8754 <user>@192.168.100.202")
    print("     Then open the URL in your browser — code is captured automatically.")
    print()
    print("  B) Manual paste: open the URL, authorize, browser will fail to load")
    print("     localhost:8754 — copy the full URL from the address bar and paste below.")
    print()
    print(f"Open this URL in your browser:")
    print(f"  {auth_url}")
    print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # Wait up to 90 s for automatic capture; then fall back to manual paste
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    server_thread.join(timeout=90)

    code  = captured.get("code", "")
    error = captured.get("error", "")

    if not code and not error:
        print()
        print("Automatic capture timed out (browser redirect didn't reach this server).")
        print("Paste the full redirect URL from your browser address bar:")
        redirect_url = input("  URL: ").strip()
        parsed_manual = urllib.parse.urlparse(redirect_url)
        qs_manual     = urllib.parse.parse_qs(parsed_manual.query)
        code  = (qs_manual.get("code")  or [""])[0]
        error = (qs_manual.get("error") or [""])[0]
        captured["state"] = (qs_manual.get("state") or [""])[0]

    if error:
        print(f"ERROR from Shutterstock: {error}")
        sys.exit(1)
    if not code:
        print("ERROR: No authorization code received.")
        sys.exit(1)
    if captured.get("state") != state:
        print("WARNING: State mismatch — possible CSRF. Aborting.")
        sys.exit(1)

    print("Code received. Exchanging for tokens...")

    body = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "client_id":     client_id,
        "client_secret": client_secret,
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        SS_TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Token exchange failed — HTTP {e.code}: {e.read().decode()}")
        sys.exit(1)

    if "refresh_token" not in tokens:
        print(f"ERROR: No refresh_token in response: {tokens}")
        sys.exit(1)

    refresh_token = tokens["refresh_token"]
    access_token  = tokens["access_token"]
    print()
    print("Authorization successful!")
    print(f"  access_token:  {access_token[:30]}…")
    print(f"  refresh_token: {refresh_token[:30]}…")

    update_env(ENV_FILE, "SHUTTERSTOCK_REFRESH_TOKEN", refresh_token)
    print()
    print(f"Saved SHUTTERSTOCK_REFRESH_TOKEN to {ENV_FILE}")
    print("Run shutterstock-upload.py — it will refresh the token automatically.")


if __name__ == "__main__":
    main()
