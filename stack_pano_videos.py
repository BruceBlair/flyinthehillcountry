#!/usr/bin/env python3
"""Stack both cameras' north-aligned panoramas into one timelapse per event.

cam2 (ridge view) on top, cam1 (tree line) below, each scaled to 3840 wide.
Panoramas stitched since 2026-09-24 20:35 are already rolled north-left by
stitch_known_angles.py (north_offset_deg), so the two rows line up bearing for
bearing. Frames are paired by stitch time: the camera with more panoramas
drives the timeline and the other contributes its nearest-in-time frame, so a
short outage on one camera repeats a frame rather than desyncing the video.

Usage: stack_pano_videos.py EVENT_DATE [...]      e.g. sunset_20260925
  Reads /volume1/pano_test/EVENT_DATE_cam{1,2}[_ext]/panos/pano_*.jpg and
  writes /volume1/pano_test/stacked/EVENT_DATE_stack_{30,15}fps.mp4 plus a
  1920-wide _preview.mp4.
"""
import bisect
import glob
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

ROOT = "/volume1/pano_test"
OUT_DIR = os.path.join(ROOT, "stacked")
WIDTH = 3840
GAP = 8   # black divider rows between the two cameras


def panos(event, cam):
    files = []
    for suffix in ("", "_ext"):   # _ext: a manual continuation run of the same event
        files += glob.glob(os.path.join(ROOT, f"{event}_{cam}{suffix}", "panos", "pano_*.jpg"))
    return sorted(files, key=os.path.getmtime)


def scaled(path):
    im = cv2.imread(path)
    h = int(round(WIDTH * im.shape[0] / im.shape[1] / 2)) * 2
    return cv2.resize(im, (WIDTH, h), interpolation=cv2.INTER_AREA)


def stack(event):
    top, bottom = panos(event, "cam2"), panos(event, "cam1")
    if not top or not bottom:
        print(f"{event}: skipped (cam2 {len(top)}, cam1 {len(bottom)} panoramas)")
        return False
    drive, other = (top, bottom) if len(top) >= len(bottom) else (bottom, top)
    other_t = [os.path.getmtime(f) for f in other]

    tmp = os.path.join(OUT_DIR, f".tmp_{event}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for i, f in enumerate(drive):
        t = os.path.getmtime(f)
        j = bisect.bisect_left(other_t, t)
        j = min((k for k in (j - 1, j) if 0 <= k < len(other)), key=lambda k: abs(other_t[k] - t))
        a, b = (f, other[j]) if drive is top else (other[j], f)
        img = np.vstack([scaled(a), np.zeros((GAP, WIDTH, 3), np.uint8), scaled(b)])
        img = img[: img.shape[0] // 2 * 2]
        cv2.imwrite(os.path.join(tmp, f"f_{i:05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 93])

    seq = os.path.join(tmp, "f_%05d.jpg")
    enc = ["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error"]
    for fps in (30, 15):
        subprocess.run(enc + ["-framerate", str(fps), "-i", seq, "-vf", "format=yuv420p", "-c:v", "libx264",
                              "-crf", "18", "-preset", "slow", "-movflags", "+faststart",
                              os.path.join(OUT_DIR, f"{event}_stack_{fps}fps.mp4")], check=True)
    subprocess.run(enc + ["-framerate", "30", "-i", seq, "-vf", "scale=1920:-2,format=yuv420p", "-c:v", "libx264",
                          "-crf", "23", "-preset", "slow", "-movflags", "+faststart",
                          os.path.join(OUT_DIR, f"{event}_stack_preview.mp4")], check=True)
    shutil.rmtree(tmp)
    print(f"{event}: {len(drive)} frames (cam2 {len(top)}, cam1 {len(bottom)}) -> {OUT_DIR}/{event}_stack_*.mp4")
    return True


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = [stack(e) for e in sys.argv[1:]]
    sys.exit(0 if all(ok) else 1)
