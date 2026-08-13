"""
Mode KE VEKTOR (DXF): logo raster (JPG/PNG) -> vektor bersih -> DXF + SVG + preview.
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

from .geometry import (
    svg_to_polylines_mm, write_dxf, render_preview, Polyline,
    fit_polylines, mirror_polylines, _bbox,
)


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

    # "Foreground-ness" = jarak tiap piksel dari WARNA LATAR (bukan kecerahan).
    # Kenapa: logo berwarna/gradien (mis. cincin oranye) kalau dipukul rata jadi
    # grayscale, bagian terang (oranye muda/kuning) dianggap latar putih lalu
    # pecah berantakan. Dengan mengukur beda-warna dari latar, seluruh subjek
    # berwarna jadi siluet pekat yang bersih. Untuk logo hitam-putih hasilnya sama.
    h, w = img.shape[:2]
    edges = np.concatenate([
        img[0, :, :], img[-1, :, :], img[:, 0, :], img[:, -1, :]
    ], axis=0)
    bg_color = np.median(edges, axis=0)                      # warna latar (BGR)
    diff = np.abs(img.astype(np.int16) - bg_color).max(axis=2)
    gray = (255 - diff).clip(0, 255).astype(np.uint8)        # subjek gelap, latar terang

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

    # Auto-orientasi: vtracer men-trace piksel HITAM sebagai objek. Kalau latar
    # (background) ikut hitam, seluruh bingkai gambar ikut ke-trace jadi kotak +
    # berantakan. Cek piksel tepi (biasanya = background); bila mayoritas hitam,
    # balik supaya latar selalu putih, objek hitam.
    border = np.concatenate([bw[0, :], bw[-1, :], bw[:, 0], bw[:, -1]])
    if border.mean() < 127:
        bw = cv2.bitwise_not(bw)

    # "Balik warna" manual = override untuk logo yang subjeknya memang terang.
    if invert:
        bw = cv2.bitwise_not(bw)

    # ponytail: morphological open/close dihapus — dengan polaritas teks-hitam,
    # step CLOSE mengikis coretan tipis & merusak teks kecil. Pembuangan speckle
    # sudah ditangani vtracer (filter_speckle) berdasarkan luas, tanpa merusak teks.
    cv2.imencode(".png", bw)[1].tofile(work_png)
    return used, warnings


def _poly_area(pts) -> float:
    """Luas poligon (shoelace), absolut."""
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def _drop_frame_and_speckle(polylines, size_mm):
    """Buang kontur bingkai-persegi penuh-gambar (border) dan bintik super kecil.

    Bingkai: kontur tertutup yang menutupi ~seluruh kanvas DAN berbentuk persegi
    (luasnya ~ luas bbox). Lingkaran/logo penuh-frame TIDAK ikut terbuang karena
    luasnya cuma ~78% bbox. Speckle: bbox < 0.4mm (sisa noise lolos vtracer).
    """
    w_mm, h_mm = size_mm
    out = []
    for pts, closed in polylines:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        full = bw >= 0.97 * w_mm and bh >= 0.97 * h_mm
        rect = _poly_area(pts) >= 0.95 * bw * bh
        if closed and full and rect:
            continue  # ponytail: border persegi penuh-frame, drop it
        if closed and bw < 0.4 and bh < 0.4:
            continue  # speckle sisa
        out.append((pts, closed))
    return out


def process_raster_logo(
    src_path: str,
    out_dir: str,
    stem: str,
    target_width_mm: float = 50.0,
    target_height_mm: float | None = None,
    mirror: bool = False,
    threshold: int = 128,
    auto_threshold: bool = True,
    invert: bool = False,
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
        src_path, work_png, threshold, auto_threshold, invert
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
    os.remove(work_png)  # bitmap antara, tak dipakai lagi setelah jadi SVG

    polylines, size_mm = svg_to_polylines_mm(
        svg_path, target_width_mm=target_width_mm, points_per_mm=points_per_mm
    )
    polylines = _drop_frame_and_speckle(polylines, size_mm)

    # Kepadatan titik ditentukan saat sampling, memakai skala SEBELUM bingkai dibuang.
    # Kalau subjek yang tersisa jauh lebih kecil dari bingkainya, membesarkannya lewat
    # fit_polylines menaikkan koordinat TANPA menambah titik — lingkaran 40 mm bisa
    # keluar sebagai poligon 35 sisi. Jadi bila pembesarannya besar, ulangi sampling
    # pada skala yang benar. Sekali ulang, bukan gelung: pass kedua sudah pas.
    box = _bbox(polylines)
    if box is not None:
        w_sub = box[2] - box[0]
        if w_sub > 0:
            perbesaran = target_width_mm / w_sub
            if perbesaran > 1.5:
                polylines, size2 = svg_to_polylines_mm(
                    svg_path,
                    target_width_mm=target_width_mm * perbesaran,
                    points_per_mm=points_per_mm,
                )
                polylines = _drop_frame_and_speckle(polylines, size2)

    # Skala WAJIB dihitung ulang dari kontur yang tersisa. Kalau bingkai penuh-gambar
    # ikut terbuang, skala lama membuat BINGKAI selebar target — subjeknya jadi jauh
    # lebih kecil dari yang diminta, sementara size_mm lama tetap melaporkan target.
    polylines, size_mm = fit_polylines(polylines, target_width_mm, target_height_mm)
    if not polylines:
        warnings.append("Tidak ada kontur terdeteksi. Coba matikan/hidupkan 'invert' atau ubah threshold.")

    if target_height_mm and size_mm[0] < target_width_mm - 0.05:
        warnings.append(
            f"Dibatasi tinggi maks — hasil {size_mm[0]:.1f} × {size_mm[1]:.1f} mm, "
            f"bukan {target_width_mm:.1f} mm lebar."
        )

    if mirror:
        polylines = mirror_polylines(polylines, size_mm[0])
        warnings.append("Dicermin horizontal. Catatan: berkas SVG yang diunduh TIDAK ikut dicermin — pakai DXF.")

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
    target_height_mm: float | None = None,
    mirror: bool = False,
    points_per_mm: float = 4.0,
) -> VectorResult:
    os.makedirs(out_dir, exist_ok=True)
    dxf_path = os.path.join(out_dir, f"{stem}.dxf")
    prev_after = os.path.join(out_dir, f"{stem}_after.png")

    warnings: List[str] = []
    polylines, size_mm = svg_to_polylines_mm(
        src_path,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
        points_per_mm=points_per_mm,
    )
    if not polylines:
        warnings.append("SVG tidak memuat path yang bisa dibaca (mungkin berisi teks/gambar raster).")

    if target_height_mm and size_mm[0] < target_width_mm - 0.05:
        warnings.append(
            f"Dibatasi tinggi maks — hasil {size_mm[0]:.1f} × {size_mm[1]:.1f} mm, "
            f"bukan {target_width_mm:.1f} mm lebar."
        )

    if mirror:
        polylines = mirror_polylines(polylines, size_mm[0])
        warnings.append("Dicermin horizontal. Catatan: berkas SVG yang diunduh TIDAK ikut dicermin — pakai DXF.")

    write_dxf(polylines, dxf_path)
    render_preview(polylines, size_mm, prev_after)

    return VectorResult(
        dxf_path=dxf_path,
        svg_path=src_path,
        preview_after=prev_after,
        preview_before=src_path,  # SVG sumber; browser bisa menampilkannya langsung di <img>
        size_mm=size_mm,
        n_paths=len(polylines),
        warnings=warnings,
    )


if __name__ == "__main__":
    # self-check: frame + speckle drop
    import math
    size = (40.0, 40.0)
    frame = ([(0, 0), (40, 0), (40, 40), (0, 40)], True)          # border -> drop
    speck = ([(1, 1), (1.2, 1), (1.2, 1.2), (1, 1.2)], True)      # noise  -> drop
    glyph = ([(5, 5), (15, 5), (15, 20), (5, 20)], True)          # keep
    circle = ([(20 + 20 * math.cos(t), 20 + 20 * math.sin(t))     # full-frame circle -> KEEP
               for t in [i / 64 * 2 * math.pi for i in range(64)]], True)
    kept = _drop_frame_and_speckle([frame, speck, glyph, circle], size)
    assert kept == [glyph, circle], [len(p[0]) for p in kept]
    print("ok")
