#!/usr/bin/env python3
"""
migrate-manifest.py — Add missing fields to all manifest.json entries.

Idempotent: only sets fields that are absent; never overwrites existing values.
Run once, then again safely after any future schema additions.

Fields added if missing:
  New (task 6):  status, stock_priority, published_to, ai_keywords,
                 ai_description, weather_at_capture
  Backfill:      flags, uploads, votes
"""

import json, os
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = Path(__file__).parent / "manifest.json"

NEW_FIELDS = {
    "status":            "pending",
    "stock_priority":    None,
    "published_to":      {"shutterstock": None, "adobe_stock": None},
    "ai_keywords":       [],
    "ai_description":    "",
    "weather_at_capture": None,
}

BACKFILL_FIELDS = {
    "flags":   {"crop": False, "enhance": False, "auth_hold": False},
    "uploads": {},
    "votes":   {"up": 0, "down": 0},
}

def migrate_entry(e: dict) -> dict:
    for key, default in {**BACKFILL_FIELDS, **NEW_FIELDS}.items():
        if key not in e:
            # Deep-copy mutable defaults so entries don't share references
            e[key] = json.loads(json.dumps(default))
    return e

def main():
    data = json.loads(MANIFEST.read_text())
    entries = data["entries"]
    total = len(entries)

    before = {k: sum(1 for e in entries if k in e) for k in NEW_FIELDS}

    for e in entries:
        migrate_entry(e)

    after = {k: sum(1 for e in entries if k in e) for k in NEW_FIELDS}
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Atomic write
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, MANIFEST)

    print(f"Migrated {total} entries in {MANIFEST.name}")
    print()
    print(f"{'Field':<22} {'Before':>8} {'After':>8} {'Added':>8}")
    print("-" * 50)
    for k in NEW_FIELDS:
        added = after[k] - before[k]
        print(f"  {k:<20} {before[k]:>8} {after[k]:>8} {added:>+8}")

if __name__ == "__main__":
    main()
