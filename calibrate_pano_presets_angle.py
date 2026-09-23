#!/usr/bin/env python3
"""
Angle-based PTZ preset calibration for cam2's fast panorama capture.

Supersedes calibrate_pano_presets_verified.py. That script spaced stops by
frame-diff (stop once the image changed "enough"), which tracks scene
texture, not angle: the 2026-09-23 live run produced gaps of 4-8 nudges and
covered only ~232deg of the ~355deg pan range (Ppos 2592 -> 849), leaving
the Ppos 849 -> 0 sector uncaptured.

cam2 reports its absolute pan position via GetPtzCurPos (Ppos), measured
2026-09-23: left limit = 2700, right limit = 0, "Right" decreases Ppos
(~7.6 Ppos units per degree over a ~355deg range). This script drives to the left limit, then
closes the loop on Ppos to hit evenly spaced targets and saves presets
there. Measured Ppos per preset is written to PRESET_JSON so math-based
stitching can use known angles instead of feature matching.

One-time run. Saves presets ids 5-9 (pano1-pano5), reused by
pano_fast_capture.sh.
"""
import json
import signal
import sys
import time

import requests
import urllib3

urllib3.disable_warnings()

ENV_PATH = "/home/HighlyReflective/hithc-gtn-depot/.env"
PRESET_JSON = "/home/HighlyReflective/hithc-gtn-depot/data/pano_presets_cam2.json"


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


env = load_env(ENV_PATH)
CAM_IP = env["CAMERA2_IP"]
CAM_USER = env["CAMERA2_USER"]
CAM_PASS = env["CAMERA2_PASSWORD"]

BASE = f"http://{CAM_IP}/cgi-bin/api.cgi"
# 5 stops @ 72deg with the 104deg wide lens = 32deg (~31%) overlap per pair,
# including the wraparound pair.
PRESET_IDS = [5, 6, 7, 8, 9]
PRESET_NAMES = ["pano1", "pano2", "pano3", "pano4", "pano5"]
PPOS_LEFT = 2700          # measured left mechanical limit
PPOS_RIGHT = 0            # measured right mechanical limit
PAN_RANGE_DEG = 355.0     # Ppos 0 and 2700 views differ by ~5deg (verified visually 2026-09-23)
UNITS_PER_DEG = (PPOS_LEFT - PPOS_RIGHT) / PAN_RANGE_DEG
TOLERANCE = 16            # ~2deg; exact Ppos is recorded in PRESET_JSON, so math-based stitching uses the true angle
FAST_SPEED = 32
SLOW_SPEED = 3
SLOW_ZONE = 150           # switch to SLOW_SPEED within this many units of target
POLL_SEC = 0.1
MAX_CORRECTIONS = 6


def login():
    r = requests.post(
        BASE + "?cmd=Login",
        json=[{"cmd": "Login", "param": {"User": {"userName": CAM_USER, "password": CAM_PASS}}}],
        timeout=8, verify=False,
    ).json()
    return r[0]["value"]["Token"]["name"]


def rapi(token, cmd, param):
    r = requests.post(
        BASE + f"?cmd={cmd}&token={token}",
        json=[{"cmd": cmd, "action": 0, "param": param}],
        timeout=8, verify=False,
    ).json()
    return r[0]


def ptz(token, op, speed=FAST_SPEED):
    return rapi(token, "PtzCtrl", {"channel": 0, "op": op, "speed": speed})


def ppos(token):
    return rapi(token, "GetPtzCurPos", {"channel": 0, "PtzCurPos": {"channel": 0}})["value"]["PtzCurPos"]["Ppos"]


def settle(token, max_wait=20.0):
    """Poll until Ppos stops changing; return the settled value."""
    last = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        p = ppos(token)
        if p == last:
            return p
        last = p
        time.sleep(0.4)
    return last


def save_preset(token, preset_id, name):
    rapi(token, "SetPtzPreset", {"channel": 0, "PtzPreset": {"channel": 0, "enable": 1, "id": preset_id, "name": name}})


def drive_to_limit(token, op):
    ptz(token, op)
    last, stable = None, 0
    for _ in range(240):
        time.sleep(0.5)
        p = ppos(token)
        stable = stable + 1 if p == last else 0
        last = p
        if stable >= 4:
            break
    ptz(token, "Stop")
    return settle(token)


def move_to(token, target):
    """Closed-loop pan to target Ppos. Right decreases Ppos, Left increases."""
    pos = settle(token)
    for _ in range(MAX_CORRECTIONS):
        err = pos - target
        if abs(err) <= TOLERANCE:
            break
        op = "Right" if err > 0 else "Left"
        speed = FAST_SPEED if abs(err) > SLOW_ZONE else SLOW_SPEED
        ptz(token, op, speed)
        while True:
            time.sleep(POLL_SEC)
            p = ppos(token)
            remaining = (p - target) if op == "Right" else (target - p)
            if remaining <= (SLOW_ZONE if speed == FAST_SPEED else TOLERANCE // 2):
                break
        ptz(token, "Stop")
        pos = settle(token)
    return pos


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    # kill sends SIGTERM, which skips finally by default -- convert it so AI
    # detect/track is always restored (same pattern as the verified script).
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    # Space stops evenly around the full 360deg circle, not across the 355deg
    # pan range: spreading to both limits would put the first and last stops
    # only ~5deg apart. With 360/n spacing the wraparound gap (last stop back
    # to the first) equals every other gap.
    n = len(PRESET_IDS)
    step = 360.0 / n * UNITS_PER_DEG
    targets = [round(PPOS_LEFT - i * step) for i in range(n)]

    token = login()
    print(f"[{time.strftime('%H:%M:%S')}] logged in; targets={targets} (~{step / UNITS_PER_DEG:.0f}deg apart)")

    # AI detect/track left enabled can hijack the PTZ mid-sweep (root-caused
    # 2026-09-22) -- disable for the run, restore in finally.
    rapi(token, "SetAiCfg", {"channel": 0, "AiDetectType": {"people": 0, "vehicle": 0, "dog_cat": 0}})
    rapi(token, "SetAutoTrackCfg", {"channel": 0, "AutoTrackCfg": {"enable": 0}})

    results = []
    try:
        left = drive_to_limit(token, "Left")
        print(f"[{time.strftime('%H:%M:%S')}] left limit Ppos={left}")

        for pid, name, target in zip(PRESET_IDS, PRESET_NAMES, targets):
            got = move_to(token, target)
            save_preset(token, pid, name)
            flag = "" if abs(got - target) <= TOLERANCE else "  WARNING: outside tolerance"
            print(f"[{time.strftime('%H:%M:%S')}] preset {pid} ({name}): target={target} Ppos={got}{flag}")
            results.append({"id": pid, "name": name, "target": target, "ppos": got,
                            "deg": round((PPOS_LEFT - got) / UNITS_PER_DEG, 1)})
    finally:
        rapi(token, "SetAiCfg", {"channel": 0, "AiDetectType": {"people": 1, "vehicle": 1, "dog_cat": 1}})
        rapi(token, "SetAutoTrackCfg", {"channel": 0, "AutoTrackCfg": {"enable": 1}})
        print(f"[{time.strftime('%H:%M:%S')}] AI detect/track restored")

    with open(PRESET_JSON, "w") as f:
        json.dump({"calibrated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "units_per_deg": UNITS_PER_DEG, "presets": results}, f, indent=2)
    print(f"\nwrote {PRESET_JSON}")
    print("preset  target  ppos   deg")
    for r in results:
        print(f"{r['id']:>6}  {r['target']:>6}  {r['ppos']:>4}  {r['deg']:>5}")
    return 0 if all(abs(r["ppos"] - r["target"]) <= TOLERANCE for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
