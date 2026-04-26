"""Reads/writes stock_manifest.json; tracks processed images."""

import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILENAME = "stock_manifest.json"


def _path(stock_ready_dir: Path) -> Path:
    return stock_ready_dir / MANIFEST_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load(stock_ready_dir: Path) -> dict:
    """Load manifest from stock_ready_dir, or return an empty structure."""
    p = _path(stock_ready_dir)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"generated": _now_iso(), "images": []}


def save(manifest: dict, stock_ready_dir: Path) -> None:
    """Write manifest to stock_ready_dir/stock_manifest.json."""
    manifest["generated"] = _now_iso()
    stock_ready_dir.mkdir(parents=True, exist_ok=True)
    with open(_path(stock_ready_dir), "w") as f:
        json.dump(manifest, f, indent=2)


def is_processed(manifest: dict, source: Path) -> bool:
    """Return True if source path already has an entry."""
    source_str = str(source)
    return any(e["source"] == source_str for e in manifest["images"])


def add_entry(manifest: dict, entry: dict) -> None:
    """Add entry, or replace existing entry with the same source path."""
    source_str = entry["source"]
    for i, existing in enumerate(manifest["images"]):
        if existing["source"] == source_str:
            manifest["images"][i] = entry
            return
    manifest["images"].append(entry)
