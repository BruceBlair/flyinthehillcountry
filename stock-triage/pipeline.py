"""Orchestrates one image through the full triage pipeline."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from naming import build_output_path, derive_label_and_category
from ocr import detect_overlay_bounds

log = logging.getLogger("pipeline")

JPEG_QUALITY = 95

_NIGHTTIME_CATEGORIES = {"stars"}


def _enhance_nighttime(img: Image.Image) -> Image.Image:
    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    return img


def process_image(
    source: Path,
    source_root: Path,
    stock_ready_dir: Path,
    location: str,
    min_resolution_mp: float = 4.0,
    ocr_top_pct: float = 0.15,
    ocr_bottom_pct: float = 0.10,
) -> dict:
    """
    Run the full pipeline for one image. Returns a manifest entry dict.
    Does NOT write to the manifest — caller does that.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    with Image.open(source) as img:
        w, h = img.size
        mp = round((w * h) / 1_000_000, 2)

        if mp < min_resolution_mp:
            return {
                "source": str(source),
                "output": None,
                "status": "rejected_resolution",
                "reason": f"{mp:.1f}MP below minimum {min_resolution_mp}MP",
                "crop_top_px": 0,
                "crop_bottom_px": 0,
                "resolution_mp": mp,
                "processed_at": now,
            }

        crop_top, crop_bot = detect_overlay_bounds(img, ocr_top_pct, ocr_bottom_pct)
        has_overlay = crop_top > 0 or crop_bot > 0
        file_status = "crop" if has_overlay else "clean"
        manifest_status = "cropped" if has_overlay else "clean"

        _, category = derive_label_and_category(source, source_root)
        output = build_output_path(source, source_root, stock_ready_dir, location, file_status)
        output.parent.mkdir(parents=True, exist_ok=True)

        exif = img.info.get("exif", b"")

        if has_overlay:
            bottom_edge = h - crop_bot if crop_bot > 0 else h
            out_img = img.crop((0, crop_top, w, bottom_edge))
        else:
            out_img = img.copy()

        if category in _NIGHTTIME_CATEGORIES:
            out_img = _enhance_nighttime(out_img)

        out_img.save(output, "JPEG", quality=JPEG_QUALITY, exif=exif)

    return {
        "source": str(source),
        "output": str(output),
        "status": manifest_status,
        "reason": (
            f"overlay detected top={crop_top}px bottom={crop_bot}px"
            if has_overlay else "no overlay detected"
        ),
        "crop_top_px": crop_top,
        "crop_bottom_px": crop_bot,
        "resolution_mp": mp,
        "processed_at": now,
    }
