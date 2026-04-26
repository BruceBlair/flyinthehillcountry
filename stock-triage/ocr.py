"""OCR band detection: returns (crop_top_px, crop_bottom_px) for a PIL image."""

import re

import pytesseract
from PIL import Image

_DATE_RE = re.compile(r"\d{4}[/\-]\d{2}")


def detect_overlay_bounds(
    image: Image.Image,
    top_pct: float = 0.15,
    bottom_pct: float = 0.10,
) -> tuple[int, int]:
    """
    Scan top and bottom bands for Reolink camera overlay text.

    Returns (crop_top_px, crop_bottom_px):
      crop_top_px    — rows to remove from the top of the image (0 if none).
      crop_bottom_px — rows to remove from the bottom of the image (0 if none).
    """
    w, h = image.size
    top_band_h = int(h * top_pct)
    bot_band_h = int(h * bottom_pct)

    top_band = image.crop((0, 0, w, top_band_h))
    bot_band = image.crop((0, h - bot_band_h, w, h))

    crop_top = _band_crop_px(top_band, band_height=top_band_h, from_top=True)
    crop_bot = _band_crop_px(bot_band, band_height=bot_band_h, from_top=False)

    return crop_top, crop_bot


def _band_crop_px(band: Image.Image, band_height: int, from_top: bool) -> int:
    """
    Run Tesseract on band. If a date pattern is found, return pixels to crop.
    from_top=True  → return rows to remove from image top (= bottom of lowest text + 2px).
    from_top=False → return rows to remove from image bottom (= band_height - top of highest text + 2px).
    """
    data = pytesseract.image_to_data(band, output_type=pytesseract.Output.DICT)

    words = [
        (data["text"][i], data["top"][i], data["height"][i])
        for i in range(len(data["text"]))
        if data["text"][i].strip() and int(data["conf"][i]) > 0
    ]

    if not words:
        return 0

    full_text = " ".join(w for w, _, _ in words)
    if not _DATE_RE.search(full_text):
        return 0

    if from_top:
        lowest_bottom = max(top + h for _, top, h in words)
        return min(lowest_bottom + 2, band_height)
    else:
        highest_top = min(top for _, top, _ in words)
        return min(band_height - highest_top + 2, band_height)
