#!/usr/bin/env python3
"""
Verify-as-you-go PTZ preset calibration for cam2's fast panorama capture.

Root cause found live on 2026-09-22: cam2's AI detect/track was left enabled
during earlier calibration attempts, so anything moving in frame could grab
the PTZ mid-sweep, then the camera's own auto-track-loss behavior
(aiStopBackTime) pulled it back after losing the subject -- looked exactly
like "stops partway through the sweep, then steps back," confirmed by direct
visual observation while a run was in progress. pano_timelapse.sh already
disabled AI detect/track before moving; this script now does too (see main()).

Frame-diff verification is still worth keeping even with AI tracking off: it
self-corrects for any other run-to-run PTZ timing variance rather than
trusting a fixed nudge duration.

One-time run. Saves 6 presets (ids 5-10, names pano1-pano6) reused by
pano_fast_capture.sh for repeatable fast timelapse captures.
"""
import io
import os
import random
import signal
import sys
import time

import requests
import urllib3
from PIL import Image, ImageChops, ImageStat

urllib3.disable_warnings()

ENV_PATH = "/home/HighlyReflective/hithc-gtn-depot/.env"


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
STEPS = 6
PRESET_IDS = [5, 6, 7, 8, 9, 10]
PRESET_NAMES = ["pano1", "pano2", "pano3", "pano4", "pano5", "pano6"]
PTZ_SPEED = 5
NUDGE_SEC = 0.497       # baseline single-nudge duration
STABILIZE = 2.0
TARGET_DIFF = 27.0      # matches the healthy 27-36 range seen in the first good run
MAX_NUDGES_PER_STOP = 10  # safety cap so we never spin forever near a hard stop
DIFF_SIZE = (400, 225)


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


def ptz(token, op):
    return rapi(token, "PtzCtrl", {"channel": 0, "op": op, "speed": PTZ_SPEED})


def snap(token):
    resp = requests.get(
        BASE + f"?cmd=Snap&channel=0&rs={random.randint(0,999999)}&token={token}",
        timeout=8, verify=False,
    )
    return Image.open(io.BytesIO(resp.content)).convert("L").resize(DIFF_SIZE)


def frame_diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def save_preset(token, preset_id, name):
    rapi(token, "SetPtzPreset", {"channel": 0, "PtzPreset": {"channel": 0, "enable": 1, "id": preset_id, "name": name}})


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    # `kill <pid>` sends SIGTERM, which by default terminates the process
    # without running the finally block below -- stopping a stuck run cleanly
    # (as done twice live on 2026-09-22) would otherwise silently skip
    # re-enabling AI detect/track. Convert SIGTERM to KeyboardInterrupt so
    # finally always runs.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    token = login()
    print(f"[{time.strftime('%H:%M:%S')}] logged in")

    # Disable AI detect/track before moving the PTZ -- left enabled, anything
    # moving in frame (bird, headlights, tree motion) can grab the camera
    # mid-sweep and drive it off course, then the camera's own
    # auto-track-loss behavior (aiStopBackTime) pulls it back after losing
    # the subject. This produced exactly the "stops partway, steps back"
    # behavior seen live on 2026-09-22 before this fix. pano_timelapse.sh
    # already does this; this script and calibrate_pano_presets.sh did not.
    print(f"[{time.strftime('%H:%M:%S')}] disabling AI detect/track")
    rapi(token, "SetAiCfg", {"channel": 0, "AiDetectType": {"people": 0, "vehicle": 0, "dog_cat": 0}})
    rapi(token, "SetAutoTrackCfg", {"channel": 0, "AutoTrackCfg": {"enable": 0}})

    results = []
    try:
        print(f"[{time.strftime('%H:%M:%S')}] driving to start position")
        ptz(token, "Left")
        time.sleep(4.5)
        ptz(token, "Stop")
        time.sleep(STABILIZE)

        # Stop 0: anchor position, no verification needed.
        frame = snap(token)
        save_preset(token, PRESET_IDS[0], PRESET_NAMES[0])
        print(f"[{time.strftime('%H:%M:%S')}] stop 0: saved preset {PRESET_IDS[0]} ({PRESET_NAMES[0]}) -- anchor")
        results.append((0, 0, None))
        prev_frame = frame

        for i in range(1, STEPS):
            nudges = 0
            diff = 0.0
            while nudges < MAX_NUDGES_PER_STOP:
                ptz(token, "Right")
                time.sleep(NUDGE_SEC)
                ptz(token, "Stop")
                time.sleep(STABILIZE)
                nudges += 1

                candidate = snap(token)
                diff = frame_diff(prev_frame, candidate)
                if diff >= TARGET_DIFF:
                    break

            if nudges >= MAX_NUDGES_PER_STOP and diff < TARGET_DIFF:
                print(f"[{time.strftime('%H:%M:%S')}] stop {i}: WARNING hit nudge cap ({nudges}) "
                      f"without reaching target diff (got {diff:.1f}, wanted {TARGET_DIFF}) "
                      f"-- likely near mechanical limit, saving anyway")

            save_preset(token, PRESET_IDS[i], PRESET_NAMES[i])
            print(f"[{time.strftime('%H:%M:%S')}] stop {i}: saved preset {PRESET_IDS[i]} ({PRESET_NAMES[i]}) "
                  f"after {nudges} nudge(s), diff={diff:.1f}")
            results.append((i, nudges, diff))
            prev_frame = candidate
    finally:
        # Restore AI detect/track to its normal (enabled) state even if the
        # sweep above is interrupted (Ctrl-C, kill, or an exception) --
        # otherwise an aborted run silently leaves AI tracking off.
        print(f"[{time.strftime('%H:%M:%S')}] re-enabling AI detect/track")
        rapi(token, "SetAiCfg", {"channel": 0, "AiDetectType": {"people": 1, "vehicle": 1, "dog_cat": 1}})
        rapi(token, "SetAutoTrackCfg", {"channel": 0, "AutoTrackCfg": {"enable": 1}})

    print(f"\n[{time.strftime('%H:%M:%S')}] calibration complete")
    print("stop  nudges  diff_vs_prev")
    for i, nudges, diff in results:
        d = f"{diff:.1f}" if diff is not None else "-- (anchor)"
        print(f"{i:>4}  {nudges:>6}  {d}")


if __name__ == "__main__":
    main()
