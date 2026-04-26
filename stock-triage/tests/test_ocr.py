import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))
from ocr import detect_overlay_bounds

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _clean_image(width=3840, height=2160):
    return Image.new("RGB", (width, height), color=(80, 130, 180))


def _image_with_top_overlay(width=3840, height=2160):
    img = Image.new("RGB", (width, height), color=(80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (width, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    return img


def _image_with_both_overlays(width=3840, height=2160):
    img = _image_with_top_overlay(width, height)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, height - 60), (width, height)], fill=(0, 0, 0))
    draw.text((20, height - 52), "2026/04/25  REOLINK", fill=(255, 255, 255), font=font)
    return img


def test_clean_image_returns_zero_zero():
    top, bot = detect_overlay_bounds(_clean_image())
    assert top == 0
    assert bot == 0


def test_top_overlay_detected():
    top, bot = detect_overlay_bounds(_image_with_top_overlay())
    assert top > 0, "expected top crop > 0 for image with timestamp overlay"
    assert bot == 0


def test_both_overlays_detected():
    top, bot = detect_overlay_bounds(_image_with_both_overlays())
    assert top > 0
    assert bot > 0


def test_top_crop_does_not_exceed_band():
    top, _ = detect_overlay_bounds(_image_with_top_overlay(3840, 2160), top_pct=0.15)
    assert top <= int(2160 * 0.15) + 10


def test_bottom_crop_does_not_exceed_band():
    _, bot = detect_overlay_bounds(_image_with_both_overlays(3840, 2160), bottom_pct=0.10)
    assert bot <= int(2160 * 0.10) + 10


def test_small_top_pct_misses_overlay_below_band():
    # text starts at y=8; a 0.3% band is ~6px — ends before the glyph, so nothing detected
    img = _image_with_top_overlay(3840, 2160)
    top, _ = detect_overlay_bounds(img, top_pct=0.003)
    assert top == 0
