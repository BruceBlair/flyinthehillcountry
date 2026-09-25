#!/usr/bin/env python3
"""
Known-angle panorama stitcher for cam2 (no feature matching).

Hugin/cpfind stitching fails on low-texture scenes (blank daylight sky) because
it has to *discover* how frames relate. cam2 already knows: each frame comes
from a preset whose pan angle was measured by calibrate_pano_presets_angle.py
(data/pano_presets_cam2.json). This script projects every frame onto a
cylinder and drops it at its measured yaw, then gain-compensates and feathers
the overlaps. Geometry is identical every cycle, so it works in any light.

The lens model (focal length f, radial distortion k1, camera pitch, vignetting,
and yaw_scale -- the true pan span vs the assumed 355deg) is fitted
once with --fit-lens by minimising overlap mismatch across all adjacent pairs,
including the wraparound pair, and saved into the preset JSON under "lens".

Usage:
  stitch_known_angles.py FRAME_DIR [-o out.jpg]      # stitch frame_00..04.jpg
  stitch_known_angles.py FRAME_DIR --fit-lens        # fit + save lens model
  stitch_known_angles.py FRAME_DIR --presets data/pano_presets_cam2_tilt16.json \
      --fit-pitch --lens-from data/pano_presets_cam2.json   # new tilt: refit pitch only

Current lens values (incl. roll and the pan-axis lean) came from a joint fit
across the level and ~16deg-up captures of 2026-09-23.
"""
import argparse
import glob
import json
import math
import os
import sys
import time

import cv2
import numpy as np

PRESET_JSON = "/home/HighlyReflective/hithc-gtn-depot/data/pano_presets_cam2.json"
HFOV_DEG = 104.0          # cam2 wide lens, per user 2026-09-23
FIT_SCALE = 0.25          # fit on 960x540 frames for speed


def default_lens(width):
    return {"f": (width / 2) / math.tan(math.radians(HFOV_DEG / 2)), "k1": 0.0, "pitch_deg": 0.0, "vig": 0.0,
            "yaw_scale": 1.0}


def effective_angles(angles, lens):
    """Scale measured pan angles by the fitted yaw_scale.

    Preset degrees assume Ppos 0..2700 spans 355deg (visual estimate); the
    true span is fitted here, since a few percent error accumulates to
    several degrees by the last stop."""
    return [a * lens.get("yaw_scale", 1.0) for a in angles]


def vignette_gain(h, w, vig):
    """Radial light-falloff correction: gain 1 + vig*r^2, r = 1 at the frame corner."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2)
    return (1 + vig * r2)[..., None]


def yaw_matrix(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def cyl_maps(w, h, lens, scale=1.0, yaw_deg=0.0):
    """Remap tables taking a frame into cylinder coords centred on its own yaw.

    Output column u maps to yaw theta=(u-cx)/f, row v to height (v-cy)/f.
    If the pan axis itself leans (axis_tilt_deg towards axis_az_deg -- a mount
    that isn't plumb), each ray is first rotated by that lean as seen from this
    frame's yaw, so the correction differs per frame. Then the ray is pitched,
    projected through a pinhole and pushed through two-term radial distortion
    (k1, k2) to find the source pixel.
    """
    f = lens["f"] * scale
    k1 = lens["k1"]
    pitch = math.radians(lens["pitch_deg"])
    half = math.radians(HFOV_DEG / 2) * 1.08   # slight margin past nominal FOV
    out_w = int(2 * half * f)
    out_h = h
    cx, cy = w / 2, h / 2
    u = (np.arange(out_w) - out_w / 2) / f
    v = (np.arange(out_h) - out_h / 2) / f
    th, hh = np.meshgrid(u, v)
    x, y, z = np.sin(th), hh, np.cos(th)
    tilt = math.radians(lens.get("axis_tilt_deg", 0.0))
    if tilt:
        az = math.radians(lens.get("axis_az_deg", 0.0))
        ra = cv2.Rodrigues(np.array([math.cos(az), 0.0, math.sin(az)]) * tilt)[0]
        ry = yaw_matrix(math.radians(yaw_deg))
        m = ry.T @ ra.T @ ry
        x, y, z = (m[0, 0] * x + m[0, 1] * y + m[0, 2] * z,
                   m[1, 0] * x + m[1, 1] * y + m[1, 2] * z,
                   m[2, 0] * x + m[2, 1] * y + m[2, 2] * z)
    # pitch: rotate ray about the camera x axis
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    # roll: camera head rotated about its optical axis (horizon slopes in-frame)
    roll = math.radians(lens.get("roll_deg", 0.0))
    if roll:
        cr, sr = math.cos(roll), math.sin(roll)
        x, y = x * cr - y * sr, x * sr + y * cr
    valid = z > 1e-3
    z = np.where(valid, z, 1e-3)
    xn, yn = x / z, y / z
    r2 = xn * xn + yn * yn
    d = 1 + k1 * r2 + lens.get("k2", 0.0) * r2 * r2
    mx = (f * xn * d + cx).astype(np.float32)
    my = (f * yn * d + cy).astype(np.float32)
    mx[~valid] = -1
    return mx, my, out_w


def load_angles(n):
    with open(PRESET_JSON) as fh:
        data = json.load(fh)
    return data, [p["deg"] for p in data["presets"][:n]]


def warp_all(frames, lens, scale, angles):
    h, w = frames[0].shape[:2]
    per_frame = bool(lens.get("axis_tilt_deg", 0.0))
    if not per_frame:
        mx, my, out_w = cyl_maps(w, h, lens, scale)
    warped, masks = [], []
    ones = np.full((h, w), 255, np.uint8)
    gain = vignette_gain(h, w, lens.get("vig", 0.0))
    for fr, ang in zip(frames, angles):
        if per_frame:
            mx, my, out_w = cyl_maps(w, h, lens, scale, ang)
        warped.append(cv2.remap(fr.astype(np.float32) * gain, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT))
        masks.append(cv2.remap(ones, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT) > 0)
    return warped, masks, out_w


def place(angles, f, out_w, pano_w):
    """Left column of each warped frame on the 360deg canvas."""
    return [int(round(math.radians(a) * f - out_w / 2)) % pano_w for a in angles]


def overlap_cost(frames_small, angles, lens, scale):
    """Mean abs grey difference over every adjacent overlap (incl. wraparound)."""
    eff = effective_angles(angles, lens)
    warped, masks, out_w = warp_all(frames_small, lens, scale, eff)
    f = lens["f"] * scale
    pano_w = int(round(2 * math.pi * f))
    x0 = place(eff, f, out_w, pano_w)
    grey = [cv2.cvtColor(w, cv2.COLOR_BGR2GRAY) for w in warped]
    total, count = 0.0, 0
    n = len(frames_small)
    for i in range(n):
        j = (i + 1) % n
        shift = (x0[j] - x0[i]) % pano_w      # j's offset relative to i
        if shift >= out_w:
            return 1e9                        # no overlap at all: invalid lens
        a, b = grey[i][:, shift:], grey[j][:, :out_w - shift]
        m = masks[i][:, shift:] & masks[j][:, :out_w - shift]
        if m.sum() < 1000:
            return 1e9
        # gain-normalise the pair so exposure differences don't dominate
        ga, gb = a[m].mean(), b[m].mean()
        total += np.abs(a[m] / ga - b[m] / gb).mean()
        count += 1
    return total / count


FIT_STEPS = {"f": 150.0, "k1": 0.08, "k2": 0.02, "pitch_deg": 4.0, "vig": 0.3,
             "yaw_scale": 0.02, "roll_deg": 1.0}


def fit_lens(frames, angles, lens, keys):
    """Coordinate descent on the given lens keys, halving step sizes each round."""
    small = [cv2.resize(fr, None, fx=FIT_SCALE, fy=FIT_SCALE, interpolation=cv2.INTER_AREA) for fr in frames]
    lens = dict(lens)
    best = overlap_cost(small, angles, lens, FIT_SCALE)
    print(f"start  cost={best:.4f}")
    steps = {k: FIT_STEPS[k] for k in keys}
    for rnd in range(6):
        for key in keys:
            for sgn in (1, -1):
                while True:
                    trial = dict(lens)
                    trial[key] += sgn * steps[key]
                    c = overlap_cost(small, angles, trial, FIT_SCALE)
                    if c < best - 1e-5:
                        lens, best = trial, c
                    else:
                        break
        print(f"round {rnd}  " + " ".join(f"{k}={lens[k]:.4g}" for k in keys) + f"  cost={best:.4f}")
        for key in steps:
            steps[key] /= 2
    return lens, best


def stitch(frames, angles, lens):
    eff = effective_angles(angles, lens)
    warped, masks, out_w = warp_all(frames, lens, 1.0, eff)
    f = lens["f"]
    pano_w = int(round(2 * math.pi * f))
    h = frames[0].shape[0]
    x0 = place(eff, f, out_w, pano_w)
    n = len(frames)

    # Gain compensation: solve per-frame gains so overlapping regions match,
    # anchored to a mean gain of 1 (least squares on log-gain differences).
    rows, rhs = [], []
    for i in range(n):
        j = (i + 1) % n
        shift = (x0[j] - x0[i]) % pano_w
        m = masks[i][:, shift:] & masks[j][:, :out_w - shift]
        a = warped[i][:, shift:][m].astype(np.float64).mean()
        b = warped[j][:, :out_w - shift][m].astype(np.float64).mean()
        r = np.zeros(n); r[i], r[j] = 1, -1
        rows.append(r); rhs.append(math.log(b / a))
    rows.append(np.ones(n)); rhs.append(0.0)
    log_g = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    gains = np.exp(log_g)

    # Feather weight: distance to the nearest edge of each frame's valid area,
    # in any direction, so dark vignetted corners contribute little where
    # another frame covers the same spot.
    cap = out_w * 0.2
    acc = np.zeros((h, pano_w, 3), np.float32)
    wsum = np.zeros((h, pano_w), np.float32)
    for i in range(n):
        dist = cv2.distanceTransform(masks[i].astype(np.uint8), cv2.DIST_L2, 5)
        wt = np.minimum(dist / cap, 1.0) + 1e-6 * masks[i]
        img = warped[i] * (wt * gains[i])[..., None]
        # add into the 360deg canvas, splitting where the frame wraps past 0deg
        first = min(out_w, pano_w - x0[i])
        acc[:, x0[i]:x0[i] + first] += img[:, :first]
        wsum[:, x0[i]:x0[i] + first] += wt[:, :first]
        if first < out_w:
            acc[:, :out_w - first] += img[:, first:]
            wsum[:, :out_w - first] += wt[:, first:]
    covered = wsum > 0
    pano = np.zeros_like(acc)
    pano[covered] = acc[covered] / wsum[covered][:, None]
    pano = np.clip(pano, 0, 255).astype(np.uint8)

    # Crop rows with incomplete coverage at top/bottom.
    full_rows = np.where(covered.mean(axis=1) > 0.995)[0]
    if len(full_rows):
        pano = pano[full_rows[0]:full_rows[-1] + 1]
    return pano, gains


def main():
    global PRESET_JSON
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frame_dir")
    ap.add_argument("-o", "--out")
    ap.add_argument("--presets", default=PRESET_JSON,
                    help="preset JSON (angles + lens); one per tilt, e.g. pano_presets_cam2_tilt16.json")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fit-lens", action="store_true",
                      help="fit the whole lens model from scratch and save it to --presets")
    mode.add_argument("--fit-pitch", action="store_true",
                      help="keep the lens from --lens-from (or --presets) and refit only pitch_deg; "
                           "use this when adding presets at a new camera tilt")
    ap.add_argument("--lens-from", help="preset JSON whose lens to start from with --fit-pitch")
    args = ap.parse_args()
    PRESET_JSON = args.presets

    paths = sorted(glob.glob(os.path.join(args.frame_dir, "frame_*.jpg")))
    data, angles = load_angles(len(paths))
    # Pan-only captures (pano_fast_capture.sh PANO_MOVE=pan) land within ~1.6deg
    # of the preset angle and record where they actually landed -- use that.
    landed = os.path.join(args.frame_dir, "angles.json")
    if os.path.exists(landed) and not (args.fit_lens or args.fit_pitch):
        with open(landed) as fh:
            angles = [p["deg"] for p in json.load(fh)["presets"]][:len(paths)]
    if len(paths) != len(data["presets"]):
        sys.exit(f"expected {len(data['presets'])} frames, found {len(paths)} in {args.frame_dir}")
    frames = [cv2.imread(p) for p in paths]

    if args.fit_lens or args.fit_pitch:
        t = time.time()
        if args.fit_lens:
            # The pan-axis lean (axis_tilt_deg/axis_az_deg) is left out on purpose:
            # from a single tilt it trades off against pitch and drifts to
            # implausible values. Fit it jointly across two tilts instead.
            lens, cost = fit_lens(frames, angles, default_lens(frames[0].shape[1]),
                                  ["f", "k1", "k2", "pitch_deg", "vig", "yaw_scale", "roll_deg"])
        else:
            with open(args.lens_from or PRESET_JSON) as fh:
                base = json.load(fh).get("lens")
            if not base:
                sys.exit("no lens to start from: pass --lens-from with a fitted preset JSON")
            base = {k: v for k, v in base.items() if isinstance(v, (int, float))}
            lens, cost = fit_lens(frames, angles, base, ["pitch_deg"])
        lens = {k: round(v, 4) for k, v in lens.items() if k != "fit_cost"}
        data["lens"] = {**lens, "fit_cost": round(cost, 4), "fit_from": os.path.abspath(args.frame_dir),
                        "fitted": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with open(PRESET_JSON, "w") as fh:
            json.dump(data, fh, indent=2)
        print(f"saved lens {lens} to {PRESET_JSON} ({time.time() - t:.0f}s)")
        return

    lens = data.get("lens") or default_lens(frames[0].shape[1])
    t = time.time()
    pano, gains = stitch(frames, angles, lens)
    out = args.out or os.path.join(args.frame_dir, "pano.jpg")
    cv2.imwrite(out, pano, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"{out}: {pano.shape[1]}x{pano.shape[0]} in {time.time() - t:.1f}s, "
          f"gains={[round(g, 2) for g in gains]}, lens={'fitted' if 'lens' in data else 'default'}")


if __name__ == "__main__":
    main()
