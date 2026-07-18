#!/usr/bin/env python3
"""
vote_server.py — Ground Truth Network
Tiny HTTP server that accepts viewer votes from the GitHub Pages gallery
and persists them to /highlights/votes.json.

POST /vote   {"snapshot": "weather/20240612_183045_storm_01.jpg", "vote": "up"}
GET  /votes  → returns votes.json contents (for debugging)

votes.json schema:
  { "snapshot_path": {"up": N, "down": N}, ... }

Run via Docker — see docker-compose.yml for the vote-server service.
Or standalone:
  python3 vote_server.py --port 8765 --highlights-dir /volume1/highlights
"""

import argparse
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from manifest_io import atomic_write_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vote-server")

HIGHLIGHTS_DIR = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))
PORT = int(os.getenv("VOTE_PORT", "8765"))
ALLOWED_VOTES = {"up", "down"}

_lock = threading.Lock()


def load_votes() -> dict:
    vf = HIGHLIGHTS_DIR / "votes.json"
    if vf.exists():
        try:
            return json.loads(vf.read_text())
        except Exception:
            pass
    return {}


def save_votes(votes: dict) -> None:
    vf = HIGHLIGHTS_DIR / "votes.json"
    atomic_write_json(vf, votes)
    _merge_into_manifest(votes)


def _merge_into_manifest(votes: dict) -> None:
    mf = HIGHLIGHTS_DIR / "manifest.json"
    if not mf.exists():
        return
    try:
        manifest = json.loads(mf.read_text())
        for entry in manifest.get("entries", []):
            snap = entry.get("snapshot")
            if snap and snap in votes:
                entry["votes"] = votes[snap]
        atomic_write_json(mf, manifest)
    except Exception as e:
        log.warning(f"manifest vote merge failed: {e}")


class VoteHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path != "/votes":
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            votes = load_votes()
        body = json.dumps(votes, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/vote":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, {"error": "invalid JSON"})
            return

        snapshot = payload.get("snapshot", "").strip().lstrip("/")
        vote = payload.get("vote", "").strip().lower()

        if not snapshot or vote not in ALLOWED_VOTES:
            self._respond(400, {"error": "snapshot and vote ('up'|'down') required"})
            return

        # Guard against path traversal
        try:
            (HIGHLIGHTS_DIR / snapshot).resolve().relative_to(HIGHLIGHTS_DIR.resolve())
        except ValueError:
            self._respond(400, {"error": "invalid snapshot path"})
            return

        with _lock:
            votes = load_votes()
            entry = votes.setdefault(snapshot, {"up": 0, "down": 0})
            entry[vote] = entry.get(vote, 0) + 1
            save_votes(votes)

        log.info(f"Vote  {vote:4s}  {snapshot}  (now {entry})")
        self._respond(200, {"ok": True, "votes": entry})

    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)


def main():
    global HIGHLIGHTS_DIR
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port",           type=int, default=PORT)
    ap.add_argument("--highlights-dir", default=str(HIGHLIGHTS_DIR))
    args = ap.parse_args()

    HIGHLIGHTS_DIR = Path(args.highlights_dir)
    HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("0.0.0.0", args.port), VoteHandler)
    log.info(f"Vote server listening on :{args.port}  highlights={HIGHLIGHTS_DIR}")
    log.info("POST /vote  {snapshot, vote}  |  GET /votes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
