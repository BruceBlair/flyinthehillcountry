#!/usr/bin/env python3
"""
shutterstock-auth-setup.py — One-time OAuth2 authorization for contributor uploads.

Run this ONCE on any machine with a browser (can be your laptop, not the NAS).
It will print a URL, you authorize in the browser, paste the redirect URL back,
and it saves a refresh token to .env on the NAS.

The refresh token never expires unless revoked. shutterstock-upload.py uses it
automatically to get fresh access tokens without any browser interaction.

Usage:
  python3 shutterstock-auth-setup.py
"""

import json, secrets, sys, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR    = Path(__file__).parent
ENV_FILE      = SCRIPT_DIR / ".env"
SS_AUTH_URL   = "https://www.shutterstock.com/oauth/authorize"
SS_TOKEN_URL  = "https://api.shutterstock.com/v2/oauth/access_token"
# Shutterstock requires a registered redirect URI; use localhost for CLI flows
REDIRECT_URI  = "https://oauth.pstmn.io/v1/callback"
# Scopes needed for contributor uploads
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
    """Write or replace a key=value line in .env."""
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

    # Check if redirect URI is registered
    print("IMPORTANT: Before running this, your Shutterstock app must have this")
    print(f"  Redirect URI registered: {REDIRECT_URI}")
    print(f"  Add it at: https://www.shutterstock.com/account/developers/apps")
    print()
    input("Press Enter once the redirect URI is registered...")
    print()

    # Build authorization URL
    state = secrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"{SS_AUTH_URL}?{params}"

    print("1. Open this URL in your browser:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Log in and click Authorize.")
    print("3. You'll be redirected to a page — paste the FULL redirect URL here:")
    print()

    redirect_response = input("Redirect URL: ").strip()

    # Parse code from redirect URL
    parsed   = urllib.parse.urlparse(redirect_response)
    qs       = urllib.parse.parse_qs(parsed.query)
    code     = (qs.get("code") or [""])[0]
    returned_state = (qs.get("state") or [""])[0]

    if not code:
        print("ERROR: No 'code' found in redirect URL.")
        sys.exit(1)
    if returned_state != state:
        print("WARNING: State mismatch — possible CSRF. Proceed with caution.")

    # Exchange code for tokens
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
    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read())

    if "refresh_token" not in tokens:
        print(f"ERROR: No refresh_token in response: {tokens}")
        sys.exit(1)

    refresh_token = tokens["refresh_token"]
    access_token  = tokens["access_token"]
    print()
    print(f"Authorization successful!")
    print(f"  access_token:  {access_token[:30]}…")
    print(f"  refresh_token: {refresh_token[:30]}…")

    # Save refresh token to .env
    update_env(ENV_FILE, "SHUTTERSTOCK_REFRESH_TOKEN", refresh_token)
    print()
    print(f"Saved SHUTTERSTOCK_REFRESH_TOKEN to {ENV_FILE}")
    print("You can now run shutterstock-upload.py — it will use the refresh token automatically.")

if __name__ == "__main__":
    main()
