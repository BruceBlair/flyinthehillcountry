#!/usr/bin/env python3
"""Closed-loop pan of a TrackMix to an absolute Ppos, without touching zoom.

Recalling a preset (PtzCtrl ToPos) also restores the zoom stored with it, and
this firmware has no way to save a pan/tilt-only preset -- so every preset-based
sweep reset the tele lens's zoom. Driving Left/Right against the GetPtzCurPos
readout moves pan only; tilt and zoom are left where they are.

Reuses the caller's session (env CAM_IP, PTZ_TOKEN) so it doesn't open a new
one per stop -- the camera's session limit is small.

Usage: CAM_IP=... PTZ_TOKEN=... ptz_pan_to.py TARGET_PPOS
Prints the settled Ppos and its angle in degrees (same convention as
calibrate_pano_presets_angle.py: 0deg at the left limit, Ppos 2700).
"""
import os
import sys
import time

import requests

PPOS_LEFT = 2700
UNITS_PER_DEG = 2700 / 355.0
TOLERANCE = 12            # ~1.6deg; the actual Ppos is recorded, so the stitcher uses the true angle
FAST_SPEED = 64
SLOW_SPEED = 3
SLOW_ZONE = 150           # switch to SLOW_SPEED within this many units of target
POLL_SEC = 0.1
MAX_CORRECTIONS = 6

BASE = f"http://{os.environ['CAM_IP']}/api.cgi"
TOKEN = os.environ["PTZ_TOKEN"]


def rapi(cmd, param):
    r = requests.post(f"{BASE}?cmd={cmd}&token={TOKEN}",
                      json=[{"cmd": cmd, "action": 0, "param": param}], timeout=8).json()
    return r[0]


def ptz(op, speed=FAST_SPEED):
    return rapi("PtzCtrl", {"channel": 0, "op": op, "speed": speed})


def ppos():
    return rapi("GetPtzCurPos", {"channel": 0, "PtzCurPos": {"channel": 0}})["value"]["PtzCurPos"]["Ppos"]


def settle(max_wait=20.0):
    """Poll until Ppos stops changing; return the settled value."""
    last = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        p = ppos()
        if p == last:
            return p
        last = p
        time.sleep(0.25)
    return last


def move_to(target):
    """Right decreases Ppos, Left increases."""
    pos = settle()
    for _ in range(MAX_CORRECTIONS):
        err = pos - target
        if abs(err) <= TOLERANCE:
            break
        op = "Right" if err > 0 else "Left"
        speed = FAST_SPEED if abs(err) > SLOW_ZONE else SLOW_SPEED
        ptz(op, speed)
        while True:
            time.sleep(POLL_SEC)
            p = ppos()
            remaining = (p - target) if op == "Right" else (target - p)
            if remaining <= (SLOW_ZONE if speed == FAST_SPEED else TOLERANCE // 2):
                break
        ptz("Stop")
        pos = settle()
    return pos


if __name__ == "__main__":
    got = move_to(int(sys.argv[1]))
    print(got, round((PPOS_LEFT - got) / UNITS_PER_DEG, 2))
