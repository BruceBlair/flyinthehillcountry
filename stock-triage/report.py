"""Generates triage_summary.html from the manifest."""

from pathlib import Path

REPORT_FILENAME = "triage_summary.html"


def generate(manifest: dict, stock_ready_dir: Path) -> None:
    """Write triage_summary.html to stock_ready_dir."""
    images = manifest.get("images", [])
    counts = _count_statuses(images)
    rows = _build_rows(images)
    html = _render(counts, rows, manifest.get("generated", ""))
    stock_ready_dir.mkdir(parents=True, exist_ok=True)
    (stock_ready_dir / REPORT_FILENAME).write_text(html)


def _count_statuses(images: list) -> dict:
    counts = {"clean": 0, "cropped": 0, "rejected_resolution": 0, "error": 0, "total": len(images)}
    for img in images:
        status = img.get("status", "error")
        if status in counts:
            counts[status] += 1
    return counts


def _build_rows(images: list) -> str:
    badge = {
        "clean":                "color:#7fc",
        "cropped":              "color:#fc7",
        "rejected_resolution":  "color:#f77",
        "error":                "color:#f55",
    }
    rows = []
    for img in images:
        status = img.get("status", "error")
        style = badge.get(status, "color:#aaa")
        rows.append(
            f'<tr>'
            f'<td style="{style}">{status}</td>'
            f'<td>{img.get("source","")}</td>'
            f'<td>{img.get("output") or "—"}</td>'
            f'<td>{img.get("resolution_mp",0):.1f} MP</td>'
            f'<td>{img.get("crop_top_px",0)} / {img.get("crop_bottom_px",0)}</td>'
            f'<td>{img.get("processed_at","")}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _render(counts: dict, rows: str, generated: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GTN Triage Summary</title>
<style>
body{{font-family:monospace;background:#111;color:#eee;padding:2rem}}
h1{{color:#7cf}}
.stats{{display:flex;gap:2rem;margin:1rem 0 2rem}}
.stat{{background:#222;padding:1rem 1.5rem;border-radius:6px}}
.n{{font-size:2rem;font-weight:bold}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}
th,td{{border:1px solid #333;padding:.4rem .6rem;text-align:left}}
th{{background:#222}}
tr:hover{{background:#1a1a1a}}
</style>
</head>
<body>
<h1>GTN Stock Triage Summary</h1>
<p>Generated: {generated}</p>
<div class="stats">
  <div class="stat"><div class="n">{counts['total']}</div>Total</div>
  <div class="stat"><div class="n" style="color:#7fc">{counts['clean']}</div>Clean</div>
  <div class="stat"><div class="n" style="color:#fc7">{counts['cropped']}</div>Cropped</div>
  <div class="stat"><div class="n" style="color:#f77">{counts['rejected_resolution']}</div>Rejected</div>
  <div class="stat"><div class="n" style="color:#f55">{counts['error']}</div>Errors</div>
</div>
<table>
<thead><tr>
  <th>Status</th><th>Source</th><th>Output</th>
  <th>Resolution</th><th>Crop T/B px</th><th>Processed</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>"""
