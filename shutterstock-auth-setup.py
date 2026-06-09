#!/usr/bin/env python3
"""
shutterstock-auth-setup.py — One-time OAuth2 authorization for contributor uploads.

Uses Postman's public OAuth callback (https://oauth.pstmn.io/v1/callback) as the
redirect URI — no local server needed, no port number issues.

Before running, register this redirect URI in the Shutterstock app:
  https://oauth.pstmn.io/v1/callback
  (shutterstock.com/account/developers/apps → your app → Callback URL)

Usage:
  python3 shutterstock-auth-setup.py

Steps:
  1. Script prints an authorization URL — open it in your browser
  2. Log in and click Authorize
  3. Postman's page confirms success and shows the redirect URL
  4. Copy the full URL from your browser address bar and paste it here

Saves SHUTTERSTOCK_REFRESH_TOKEN to .env when done.
"""

import json, secrets, sys, urllib.error, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
ENV_FILE     = SCRIPT_DIR / ".env"
SS_AUTH_URL  = "https://www.shutterstock.com/oauth/authorize"
SS_TOKEN_URL = "https://api.shutterstock.com/v2/oauth/access_token"
REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
SCOPES       = "user.view contributors.list collections.edit.add"


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

    state  = secrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"{SS_AUTH_URL}?{params}"

    print("Redirect URI (must be registered in your Shutterstock app):")
    print(f"  {REDIRECT_URI}")
    print()
    print("1. Open this URL in your browser:")
    print(f"   {auth_url}")
    print()
    print("2. Log in and click Authorize.")
    print("3. You'll land on a Postman page — copy the full URL from the address bar.")
    print()

    redirect_url = input("Paste the full redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    qs     = urllib.parse.parse_qs(parsed.query)
    code          = (qs.get("code")  or [""])[0]
    returned_state = (qs.get("state") or [""])[0]
    error         = (qs.get("error") or [""])[0]

    if error:
        print(f"ERROR from Shutterstock: {error}")
        sys.exit(1)
    if not code:
        print("ERROR: No 'code' found in redirect URL.")
        sys.exit(1)
    if returned_state != state:
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
