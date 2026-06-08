#!/usr/bin/env python3
"""
shutterstock-upload.py — Upload accepted manifest entries to Shutterstock.

Pipeline per entry:
  1. Enrich weather_at_capture from InfluxDB (if capture is >= 2026-06-05)
  2. Assemble keywords, description, categories
  3. Upload image file to Shutterstock (multipart POST)
  4. Submit metadata
  5. Update manifest: status=submitted, published_to.shutterstock=<id>

Usage:
  python3 shutterstock-upload.py              # process all accepted entries
  python3 shutterstock-upload.py --dry-run    # show what would be uploaded, no API calls
  python3 shutterstock-upload.py --limit 5    # process at most N entries
  python3 shutterstock-upload.py --enrich-only # only populate weather_at_capture, no upload

Credentials required in .env:
  SHUTTERSTOCK_CLIENT_ID      — from shutterstock.com/account/developers/apps
  SHUTTERSTOCK_CLIENT_SECRET  — same
  SHUTTERSTOCK_REFRESH_TOKEN  — run shutterstock-auth-setup.py once to obtain
  SHUTTERSTOCK_AUTO_PUBLISH   — set "true" to actually submit (default: false = dry-run safe)
"""

import argparse, json, os, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zoneinfo

SCRIPT_DIR     = Path(__file__).parent
MANIFEST_FILE  = SCRIPT_DIR / "manifest.json"
SNAPSHOT_ROOT  = SCRIPT_DIR
WEATHER_START  = datetime(2026, 6, 5, tzinfo=timezone.utc)
LOCAL_TZ       = zoneinfo.ZoneInfo("America/Chicago")

# ── Load .env ─────────────────────────────────────────────────────────────────
def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env

ENV_FILE = SCRIPT_DIR / ".env"
cfg = load_env(ENV_FILE)

INFLUX_URL       = f"http://{cfg['NAS_IP']}:8086"
INFLUX_TOKEN     = cfg["INFLUXDB_TOKEN"]
SS_CLIENT_ID     = cfg.get("SHUTTERSTOCK_CLIENT_ID", "")
SS_CLIENT_SECRET = cfg.get("SHUTTERSTOCK_CLIENT_SECRET", "")
SS_REFRESH_TOKEN = cfg.get("SHUTTERSTOCK_REFRESH_TOKEN", "")
AUTO_PUBLISH     = cfg.get("SHUTTERSTOCK_AUTO_PUBLISH", "false").lower() == "true"

def update_env(key: str, value: str):
    """Write or replace a key=value line in .env (preserves all other lines)."""
    lines = ENV_FILE.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            ENV_FILE.write_text("\n".join(lines) + "\n")
            return
    lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")

SS_API_BASE   = "https://api.shutterstock.com/v2"

# Shutterstock category IDs (v2 API)
# https://api.shutterstock.com/v2/images/categories
CATEGORY_MAP = {
    "weather":              [{"id": 11}],   # Nature
    "golden_hour":          [{"id": 11}],
    "golden_hour/sunrise":  [{"id": 11}],
    "golden_hour/sunset":   [{"id": 11}],
    "wildlife":             [{"id": 1}, {"id": 11}],   # Animals, Nature
}

# ── Manifest helpers ──────────────────────────────────────────────────────────
def load_manifest():
    data = json.loads(MANIFEST_FILE.read_text())
    return data, data["entries"]

def save_manifest(data):
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = MANIFEST_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, MANIFEST_FILE)

def parse_timestamp(ts: str) -> datetime:
    """Parse manifest timestamp (YYYYMMDD_HHMMSS, local America/Chicago) → UTC datetime."""
    local = datetime(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]),
                     int(ts[9:11]), int(ts[11:13]), int(ts[13:15]),
                     tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc)

# ── Weather enrichment ────────────────────────────────────────────────────────
WEATHER_ENTITIES = {
    "gw3000b_outdoor_temperature": "temp_f",
    "gw3000b_humidity":            "humidity_pct",
    "gw3000b_relative_pressure":   "pressure_msl_inhg",
    "gw3000b_wind_speed":          "wind_speed_mph",
    "gw3000b_wind_direction":      "wind_dir_deg",
    "gw3000b_wind_gust":           "wind_gust_mph",
    "gw3000b_rain_rate_piezo":     "rain_rate_in_hr",
    "gw3000b_daily_rain_piezo":    "rain_daily_in",
    "gw3000b_uv_index":            "uv_index",
}

def fetch_weather_at(utc_dt: datetime) -> dict | None:
    """Query InfluxDB for sensor readings within ±10 min of utc_dt. Returns None if no data."""
    if utc_dt < WEATHER_START:
        return None

    start = (utc_dt - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stop  = (utc_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entity_filter = "|".join(WEATHER_ENTITIES.keys())

    flux = f"""from(bucket: "sensor_data")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._field == "value")
  |> filter(fn: (r) => r.entity_id =~ /^({entity_filter})$/)
  |> last()
  |> keep(columns: ["_time", "_value", "entity_id"])"""

    url = f"{INFLUX_URL}/api/v2/query?org=ground_truth"
    req = urllib.request.Request(
        url, data=flux.encode(),
        headers={"Authorization": f"Token {INFLUX_TOKEN}",
                 "Content-Type": "application/vnd.flux"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            csv = resp.read().decode()
    except Exception as e:
        print(f"    WARNING: InfluxDB weather query failed: {e}", file=sys.stderr)
        return None

    raw = {}
    for line in csv.splitlines():
        if not line.startswith(",_result"):
            continue
        parts = line.split(",")
        try:
            raw[parts[5]] = float(parts[4])
        except (ValueError, IndexError):
            continue

    if not raw:
        return None

    result = {"timestamp": utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for entity_id, field_name in WEATHER_ENTITIES.items():
        v = raw.get(entity_id)
        result[field_name] = round(v, 2) if v is not None else None  # type: ignore[assignment]
    return result

# ── Metadata assembly ─────────────────────────────────────────────────────────
def build_description(entry: dict, weather: dict | None) -> str:
    """Build a Shutterstock-ready description from entry metadata."""
    parts = []
    label = entry.get("label", "scene").replace("_", " ")
    cats  = entry.get("categories", [])

    if "golden_hour/sunrise" in cats or entry.get("label") == "sunrise_scene":
        parts.append("Sunrise over the Texas Hill Country.")
    elif "golden_hour/sunset" in cats or entry.get("label") == "sunset_scene":
        parts.append("Sunset over the Texas Hill Country.")
    elif "golden_hour" in cats:
        parts.append("Golden hour light over the Texas Hill Country.")
    elif "weather" in cats:
        parts.append(f"Weather scene: {label} photographed in the Texas Hill Country.")
    elif "wildlife" in cats:
        parts.append(f"{label.capitalize()} photographed in the Texas Hill Country of central Texas.")
    else:
        parts.append(f"{label.capitalize()} in the Texas Hill Country.")

    parts.append("Ground Truth Network monitoring station, HITHC LLC, Blanco County, Texas.")

    if weather:
        temp = weather.get("temp_f")
        wind = weather.get("wind_speed_mph")
        humid = weather.get("humidity_pct")
        if temp:
            parts.append(f"Conditions at capture: {temp}°F, {humid}% humidity, {wind} mph wind.")

    if entry.get("ai_description"):
        parts.append(entry["ai_description"])

    return " ".join(parts)

def build_keywords(entry: dict, weather: dict | None) -> list[str]:
    """Merge existing ai_keywords with location/condition tags. Max 50 for Shutterstock."""
    kw = set(entry.get("ai_keywords") or [])

    # Location tags always present
    kw.update(["texas", "texas_hill_country", "hill_country", "blanco_county",
                "central_texas", "rural", "outdoor"])

    cats = entry.get("categories", [])
    if "golden_hour/sunrise" in cats or "sunrise" in entry.get("label",""):
        kw.update(["sunrise", "golden_hour", "dawn", "morning_light"])
    if "golden_hour/sunset" in cats or "sunset" in entry.get("label",""):
        kw.update(["sunset", "golden_hour", "dusk", "evening_light"])
    if "weather" in cats:
        kw.update(["weather", "sky", "clouds", "atmospheric"])
    if "wildlife" in cats:
        kw.update(["wildlife", "nature", "wild_animal"])

    if weather:
        if (weather.get("rain_rate_in_hr") or 0) > 0:
            kw.update(["rain", "precipitation"])
        if (weather.get("wind_speed_mph") or 0) > 20:
            kw.update(["wind", "windy"])
        uv = weather.get("uv_index") or 0
        if uv >= 6:
            kw.update(["sunny", "bright_light"])

    # Shutterstock caps at 50 keywords; space-separated, lowercase
    result = sorted(kw)[:50]
    return [k.replace("_", " ") for k in result]

# ── Shutterstock API client ───────────────────────────────────────────────────
class ShutterstockClient:
    """
    Shutterstock Contributor Upload API v2.

    Docs: https://api-reference.shutterstock.com/
    Credentials: https://www.shutterstock.com/account/developers/apps

    Required scopes: contributors.list, collections.edit.add (contributor context)
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str = ""):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._token        = None
        self._token_expiry = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        if self.refresh_token:
            # User-bound token via refresh_token grant (required for contributor uploads)
            fields = {
                "grant_type":    "refresh_token",
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }
        else:
            # App-level token (read-only; contributor uploads will fail with 403)
            fields = {
                "grant_type":    "client_credentials",
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "scope":         "contributors.list",
            }

        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(
            f"{SS_API_BASE}/oauth/access_token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        self._token        = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)

        # Shutterstock rotates refresh tokens on each use — save the new one immediately
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self.refresh_token:
            self.refresh_token = new_refresh
            update_env("SHUTTERSTOCK_REFRESH_TOKEN", new_refresh)

        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        token = self._get_token()
        url   = f"{SS_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        body    = kwargs.pop("body", None)
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            raise RuntimeError(f"Shutterstock {method} {path} → HTTP {e.code}: {detail}") from e

    def upload_image(self, image_path: Path) -> str:
        """
        Upload image bytes to Shutterstock.
        Returns upload_id to reference in the submission.

        API: POST /v2/contributor_images/upload?filename=<name>
             Content-Type: image/jpeg
             Body: raw image bytes
        Returns: {"upload_id": "..."}
        """
        data    = image_path.read_bytes()
        token   = self._get_token()
        url     = f"{SS_API_BASE}/contributor_images/upload?filename={urllib.parse.quote(image_path.name)}"
        req     = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "image/jpeg",
                "Content-Length": str(len(data)),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        return result["upload_id"]

    def submit_image(self, upload_id: str, description: str,
                     keywords: list[str], categories: list[dict],
                     editorial: bool = False) -> str:
        """
        Create an image submission with metadata.
        Returns the Shutterstock image ID.

        API: POST /v2/contributor_images
             Body: JSON with upload_id, description, keywords, categories
        Returns: {"id": "..."}
        """
        payload = {
            "upload_id":   upload_id,
            "description": description[:200],   # Shutterstock max 200 chars
            "keywords":    keywords,
            "categories":  categories,
            "editorial":   editorial,
        }
        result = self._request("POST", "/contributor_images", body=payload)
        return result["id"]

    def get_image_status(self, image_id: str) -> str:
        """
        Poll image submission review status.
        Returns one of: pending_review, approved, rejected

        API: GET /v2/contributor_images/{id}
        """
        result = self._request("GET", f"/contributor_images/{image_id}")
        return result.get("status", "unknown")

# ── Per-entry pipeline ────────────────────────────────────────────────────────
def process_entry(entry: dict, client: ShutterstockClient | None,
                  dry_run: bool, enrich_only: bool) -> dict:
    ts      = entry["timestamp"]
    utc_dt  = parse_timestamp(ts)
    snap    = entry.get("snapshot")

    print(f"\n  [{ts}] {entry.get('label')} — {snap}")

    # Step 1: weather enrichment
    if entry.get("weather_at_capture") is None:
        weather = fetch_weather_at(utc_dt)
        if weather:
            entry["weather_at_capture"] = weather  # type: ignore[assignment]
            print(f"    weather: {weather.get('temp_f')}°F, {weather.get('humidity_pct')}% RH, "
                  f"{weather.get('wind_speed_mph')} mph")
        else:
            print("    weather: no data (before Ecowitt start or out of range)")
    else:
        weather = entry["weather_at_capture"]
        print(f"    weather: already enriched")

    if enrich_only:
        return entry

    # Step 2: metadata assembly
    description = build_description(entry, weather)
    keywords    = build_keywords(entry, weather)
    cats        = entry.get("categories", ["weather"])
    categories  = CATEGORY_MAP.get(cats[0] if cats else "weather",
                                   [{"id": 11}])

    print(f"    description: {description[:80]}…")
    print(f"    keywords ({len(keywords)}): {', '.join(keywords[:6])}…")

    if dry_run:
        print(f"    [DRY RUN] would upload {snap}")
        return entry

    # Step 3: resolve image path
    if not snap:
        print(f"    SKIP: no snapshot path on entry", file=sys.stderr)
        return entry
    image_path = SNAPSHOT_ROOT / snap
    if not image_path.exists():
        print(f"    SKIP: snapshot not found at {image_path}", file=sys.stderr)
        entry["status"] = "error_missing_snapshot"
        return entry

    if not AUTO_PUBLISH or client is None:
        print(f"    SKIP: SHUTTERSTOCK_AUTO_PUBLISH=false — set to 'true' to submit")
        return entry

    # Step 4: upload + submit
    try:
        print(f"    uploading {image_path.stat().st_size // 1024}KB…")
        upload_id = client.upload_image(image_path)
        print(f"    upload_id: {upload_id}")

        ss_id = client.submit_image(upload_id, description, keywords, categories)
        print(f"    submitted: {ss_id}")

        entry["status"]                      = "submitted"
        entry["published_to"]["shutterstock"] = ss_id

    except Exception as e:
        print(f"    ERROR: {e}", file=sys.stderr)
        entry["status"] = "error_upload_failed"

    return entry

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run",     action="store_true",
                        help="Show what would be uploaded without making API calls")
    parser.add_argument("--enrich-only", action="store_true",
                        help="Only populate weather_at_capture; skip upload")
    parser.add_argument("--limit",       type=int, default=0,
                        help="Process at most N entries (0 = unlimited)")
    parser.add_argument("--status",      default="accepted",
                        help="Only process entries with this status (default: accepted)")
    args = parser.parse_args()

    if not args.dry_run and not args.enrich_only:
        if not SS_CLIENT_ID or not SS_CLIENT_SECRET:
            print("ERROR: SHUTTERSTOCK_CLIENT_ID and SHUTTERSTOCK_CLIENT_SECRET must be set in .env")
            print("       Get credentials at: https://www.shutterstock.com/account/developers/apps")
            sys.exit(1)

    data, entries = load_manifest()

    queue = [e for e in entries if e.get("status") == args.status]
    if not queue:
        print(f"No entries with status='{args.status}'. "
              f"Set entries to '{args.status}' via the content manager first.")
        print(f"(Total entries: {len(entries)}, status distribution: "
              + str({s: sum(1 for e in entries if e.get('status') == s)
                     for s in set(e.get('status') for e in entries)}) + ")")
        return

    if args.limit:
        queue = queue[:args.limit]

    print(f"Processing {len(queue)} entries (status={args.status})"
          + (" [DRY RUN]" if args.dry_run else "")
          + (" [ENRICH ONLY]" if args.enrich_only else ""))

    client = None
    if not args.dry_run and not args.enrich_only and AUTO_PUBLISH:
        if not SS_REFRESH_TOKEN:
            print("ERROR: SHUTTERSTOCK_REFRESH_TOKEN is not set in .env")
            print("       Run: python3 shutterstock-auth-setup.py")
            sys.exit(1)
        client = ShutterstockClient(SS_CLIENT_ID, SS_CLIENT_SECRET, SS_REFRESH_TOKEN)

    ts_to_entry = {e["timestamp"]: e for e in entries}
    changed = 0

    for entry in queue:
        updated = process_entry(entry, client, args.dry_run, args.enrich_only)
        ts_to_entry[entry["timestamp"]].update(updated)
        changed += 1
        # Save after each entry so a crash doesn't lose work
        if not args.dry_run:
            save_manifest(data)

    print(f"\nDone: {changed} entries processed.")
    if args.dry_run:
        print("Re-run without --dry-run (and with SHUTTERSTOCK_AUTO_PUBLISH=true) to upload.")

if __name__ == "__main__":
    main()
