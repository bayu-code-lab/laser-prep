"""
Geometri & util bersama: parsing SVG -> polyline (dalam mm), tulis DXF, render preview.
Semua koordinat internal memakai satuan milimeter (mm), sumbu Y ke ATAS (seperti EZCAD2/DXF).
"""
from __future__ import annotations
import math
import re
from typing import List, Tuple

import ezdxf
from ezdxf import units as ezunits
from PIL import Image, ImageDraw
from svgpathtools import svg2paths2

Point = Tuple[float, float]
Polyline = Tuple[List[Point], bool]  # (titik-titik, apakah tertutup)

_TRANSLATE = re.compile(r"translate\(\s*([-\d.eE]+)[ ,]+([-\d.eE]+)\s*\)")


def _apply_transform(paths, attrs):
    """vtracer menaruh tiap path pada transform=\"translate(x,y)\" yang TIDAK
    dibaca svg2paths2. Terapkan translate-nya supaya tiap kontur di posisi benar.
    (vtracer hanya memakai translate; scale/matrix diabaikan — beri warning bila ada.)
    """
    out = []
    for p, a in zip(paths, attrs):
        t = (a or {}).get("transform", "")
        m = _TRANSLATE.search(t)
        if m:
            p = p.translated(complex(float(m.group(1)), float(m.group(2))))
        out.append(p)
    return out


def svg_to_polylines_mm(
    svg_path: str,
    target_width_mm: float | None = None,
    target_height_mm: float | None = None,
    points_per_mm: float = 4.0,
) -> Tuple[List[Polyline], Tuple[float, float]]:
    """Baca file SVG, ratakan (flatten) semua path jadi polyline dalam mm.

    Mengembalikan (daftar_polyline, (lebar_mm, tinggi_mm)).
    Sumbu Y dibalik supaya orientasi benar di DXF/EZCAD2.
    """
    paths, _attrs, _svg_attr = svg2paths2(svg_path)
    paths = _apply_transform(paths, _attrs)

    # Bounding box global dalam satuan user SVG.
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    for p in paths:
        if len(p) == 0:
            continue
        try:
            x0, x1, y0, y1 = p.bbox()
        except Exception:
            continue
        xmin, xmax = min(xmin, x0), max(xmax, x1)
        ymin, ymax = min(ymin, y0), max(ymax, y1)

    if not math.isfinite(xmin) or xmax <= xmin:
        return [], (0.0, 0.0)

    src_w = xmax - xmin
    src_h = ymax - ymin

    # Tentukan skala (user unit -> mm) menjaga rasio aspek.
    if target_width_mm and target_height_mm:
        sx = target_width_mm / src_w
        sy = target_height_mm / src_h
        scale = min(sx, sy)
    elif target_width_mm:
        scale = target_width_mm / src_w
    elif target_height_mm:
        scale = target_height_mm / src_h
    else:
        scale = 1.0  # asumsi 1 user unit = 1 mm bila tak ada target

    def tx(x: float, y: float) -> Point:
        # geser ke origin, skala, balik Y
        nx = (x - xmin) * scale
        ny = (ymax - y) * scale
        return (nx, ny)

    polylines: List[Polyline] = []
    for p in paths:
        for sub in p.continuous_subpaths():
            try:
                length_uu = sub.length()
            except Exception:
                length_uu = 0.0
            length_mm = max(length_uu * scale, 0.01)
            n = int(length_mm * points_per_mm)
            n = max(8, min(n, 6000))
            pts: List[Point] = []
            for i in range(n + 1):
                c = sub.point(i / n)
                pts.append(tx(c.real, c.imag))
            closed = bool(sub.isclosed())
            # buang titik berturut yang identik
            cleaned = [pts[0]]
            for q in pts[1:]:
                if abs(q[0] - cleaned[-1][0]) > 1e-4 or abs(q[1] - cleaned[-1][1]) > 1e-4:
                    cleaned.append(q)
            if len(cleaned) >= 2:
                polylines.append((cleaned, closed))

    out_w = src_w * scale
    out_h = src_h * scale
    return polylines, (out_w, out_h)


def write_dxf(polylines: List[Polyline], out_path: str) -> None:
    """Tulis polyline (mm) ke DXF R2010, satuan milimeter, siap import EZCAD2."""
    doc = ezdxf.new("R2010")
    doc.units = ezunits.MM  # $INSUNITS = 4 (mm)
    msp = doc.modelspace()
    for pts, closed in polylines:
        msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": "ENGRAVE"})
    doc.saveas(out_path)


def render_preview(
    polylines: List[Polyline],
    size_mm: Tuple[float, float],
    out_png: str,
    canvas_px: int = 900,
    margin: int = 24,
    line_px: int = 2,
) -> None:
    """Render polyline jadi PNG hitam-putih untuk preview 'after'."""
    w_mm, h_mm = size_mm
    if w_mm <= 0 or h_mm <= 0:
        Image.new("RGB", (canvas_px, canvas_px), "white").save(out_png)
        return
    draw_w = canvas_px - 2 * margin
    draw_h = int(draw_w * (h_mm / w_mm)) if w_mm >= h_mm else draw_w
    if w_mm < h_mm:
        draw_h = canvas_px - 2 * margin
        draw_w = int(draw_h * (w_mm / h_mm))
    img_w = draw_w + 2 * margin
    img_h = draw_h + 2 * margin
    img = Image.new("RGB", (img_w, img_h), "white")
    d = ImageDraw.Draw(img)
    sx = draw_w / w_mm
    sy = draw_h / h_mm
    s = min(sx, sy)

    def to_px(pt: Point) -> Point:
        # balik Y lagi (mm Y-up -> pixel Y-down)
        px = margin + pt[0] * s
        py = margin + (h_mm - pt[1]) * s
        return (px, py)

    for pts, closed in polylines:
        seq = [to_px(p) for p in pts]
        if closed and len(seq) >= 2:
            seq = seq + [seq[0]]
        if len(seq) >= 2:
            d.line(seq, fill=(15, 15, 15), width=line_px, joint="curve")
    img.save(out_png)
