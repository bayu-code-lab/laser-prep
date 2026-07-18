"""
Cabang VEKTOR (MOPA): logo raster (JPG/PNG) -> vektor bersih -> DXF + SVG + preview.
Juga menerima input SVG (langsung diratakan & diskalakan).

Python HANYA menyiapkan geometri bersih & skala mm yang benar.
Parameter laser (power/speed/frequency/hatch) tetap kamu set di EZCAD2.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Tuple

import cv2
import numpy as np
import vtracer

from .geometry import svg_to_polylines_mm, write_dxf, render_preview, Polyline


@dataclass
class VectorResult:
    dxf_path: str
    svg_path: str
    preview_after: str
    preview_before: str
    size_mm: Tuple[float, float]
    n_paths: int
    warnings: List[str] = field(default_factory=list)


def _preprocess_bitmap(
    src_path: str,
    work_png: str,
    threshold: int = 128,
    auto_threshold: bool = True,
    invert: bool = False,
    despeckle: int = 2,
) -> Tuple[int, List[str]]:
    """Ubah logo raster jadi bitmap hitam/putih bersih untuk vtracer.

    Return (threshold_terpakai, warnings).
    """
    warnings: List[str] = []
    img = cv2.imdecode(np.fromfile(src_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Gagal membaca gambar. Format tidak didukung / file rusak.")

    # Tangani alpha: komposit di atas putih.
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        white = np.ones_like(rgb) * 255.0
        img = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)
    elif img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape
    if max(h, w) < 200:
        warnings.append(
            f"Resolusi input rendah ({w}x{h}px). Vektor mungkin kasar — minta file lebih besar bila bisa."
        )

    # Naikkan resolusi kecil agar hasil trace lebih halus.
    if max(h, w) < 1000:
        scale_up = 1000.0 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale_up, fy=scale_up, interpolation=cv2.INTER_CUBIC)

    if auto_threshold:
        used, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        used = int(used)
    else:
        used = int(threshold)
        _, bw = cv2.threshold(gray, used, 255, cv2.THRESH_BINARY)

    # Deteksi apakah subjek gelap di latar terang (umum untuk logo).
    if invert:
        bw = cv2.bitwise_not(bw)

    # Buang bintik kecil (speckle) dengan morphological opening.
    if despeckle and despeckle > 0:
        k = np.ones((despeckle, despeckle), np.uint8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k)

    cv2.imencode(".png", bw)[1].tofile(work_png)
    return used, warnings


def process_raster_logo(
    src_path: str,
    out_dir: str,
    stem: str,
    target_width_mm: float = 50.0,
    threshold: int = 128,
    auto_threshold: bool = True,
    invert: bool = False,
    despeckle: int = 2,
    filter_speckle: int = 4,
    corner_threshold: int = 60,
    points_per_mm: float = 4.0,
) -> VectorResult:
    os.makedirs(out_dir, exist_ok=True)
    work_png = os.path.join(out_dir, f"{stem}_bw.png")
    svg_path = os.path.join(out_dir, f"{stem}.svg")
    dxf_path = os.path.join(out_dir, f"{stem}.dxf")
    prev_after = os.path.join(out_dir, f"{stem}_after.png")

    used_thr, warnings = _preprocess_bitmap(
        src_path, work_png, threshold, auto_threshold, invert, despeckle
    )

    # vtracer: mode biner, kurva halus.
    vtracer.convert_image_to_svg_py(
        work_png,
        svg_path,
        colormode="binary",
        mode="spline",
        filter_speckle=int(filter_speckle),
        corner_threshold=int(corner_threshold),
        path_precision=3,
    )

    polylines, size_mm = svg_to_polylines_mm(
        svg_path, target_width_mm=target_width_mm, points_per_mm=points_per_mm
    )
    if not polylines:
        warnings.append("Tidak ada kontur terdeteksi. Coba matikan/hidupkan 'invert' atau ubah threshold.")

    write_dxf(polylines, dxf_path)
    render_preview(polylines, size_mm, prev_after)

    return VectorResult(
        dxf_path=dxf_path,
        svg_path=svg_path,
        preview_after=prev_after,
        preview_before=src_path,
        size_mm=size_mm,
        n_paths=len(polylines),
        warnings=warnings,
    )


def process_svg_input(
    src_path: str,
    out_dir: str,
    stem: str,
    target_width_mm: float = 50.0,
    points_per_mm: float = 4.0,
) -> VectorResult:
    os.makedirs(out_dir, exist_ok=True)
    dxf_path = os.path.join(out_dir, f"{stem}.dxf")
    prev_after = os.path.join(out_dir, f"{stem}_after.png")

    warnings: List[str] = []
    polylines, size_mm = svg_to_polylines_mm(
        src_path, target_width_mm=target_width_mm, points_per_mm=points_per_mm
    )
    if not polylines:
        warnings.append("SVG tidak memuat path yang bisa dibaca (mungkin berisi teks/gambar raster).")

    write_dxf(polylines, dxf_path)
    render_preview(polylines, size_mm, prev_after)

    return VectorResult(
        dxf_path=dxf_path,
        svg_path=src_path,
        preview_after=prev_after,
        preview_before=prev_after,
        size_mm=size_mm,
        n_paths=len(polylines),
        warnings=warnings,
    )
