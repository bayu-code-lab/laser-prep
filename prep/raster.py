"""
Cabang RASTER (Kaca UV): foto/gambar -> PNG grayscale bersih dengan ukuran fisik benar.

Python menyiapkan: grayscale, kontras, crop/auto-trim, penskalaan ke mm @ DPI.
DITHERING/HALFTONE sengaja TIDAK dilakukan di sini — biar EZCAD2 yang urus (lebih unggul).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


@dataclass
class RasterResult:
    png_path: str
    preview_after: str
    preview_before: str
    size_mm: Tuple[float, float]
    px: Tuple[int, int]
    dpi: int
    warnings: List[str] = field(default_factory=list)


def _try_remove_bg(bgr: np.ndarray) -> Tuple[np.ndarray, bool, str]:
    """Coba hapus background pakai rembg bila terpasang. Return (rgba/bgr, berhasil, pesan)."""
    try:
        from rembg import remove  # opsional, berat
    except Exception:
        return bgr, False, "rembg belum terpasang — lewati hapus background (lihat README)."
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    out = remove(Image.fromarray(rgb))  # RGBA
    return np.array(out), True, "Background dihapus (rembg)."


def process_photo(
    src_path: str,
    out_dir: str,
    stem: str,
    target_width_mm: float = 50.0,
    dpi: int = 600,
    remove_bg: bool = False,
    autocontrast: bool = True,
    clahe: bool = False,
    invert: bool = False,
    gamma: float = 1.0,
) -> RasterResult:
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, f"{stem}_uv.png")
    prev_before = os.path.join(out_dir, f"{stem}_before.png")
    prev_after = os.path.join(out_dir, f"{stem}_after.png")
    warnings: List[str] = []

    img = cv2.imdecode(np.fromfile(src_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Gagal membaca gambar. Format tidak didukung / file rusak.")

    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        white = np.ones_like(rgb) * 255.0
        img = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)
    elif img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # simpan preview 'before'
    cv2.imencode(".png", img)[1].tofile(prev_before)

    if remove_bg:
        rgba, ok, msg = _try_remove_bg(img)
        warnings.append(msg)
        if ok:
            # komposit di atas putih agar area kosong = putih (tak terukir)
            a = rgba[:, :, 3:4].astype(np.float32) / 255.0
            rgb = rgba[:, :, :3].astype(np.float32)
            white = np.ones_like(rgb) * 255.0
            img = (rgb * a + white * (1 - a)).astype(np.uint8)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if clahe:
        clip = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clip.apply(gray)
    elif autocontrast:
        # normalisasi rentang (mirip auto-levels)
        lo, hi = np.percentile(gray, 1), np.percentile(gray, 99)
        if hi > lo:
            gray = np.clip((gray.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)

    if abs(gamma - 1.0) > 1e-3:
        inv = 1.0 / max(gamma, 1e-3)
        table = ((np.arange(256) / 255.0) ** inv * 255).astype(np.uint8)
        gray = cv2.LUT(gray, table)

    if invert:
        gray = cv2.bitwise_not(gray)

    # Penskalaan fisik: mm -> px pada DPI.
    h, w = gray.shape
    target_w_px = max(1, int(round(target_width_mm / 25.4 * dpi)))
    scale = target_w_px / w
    target_h_px = max(1, int(round(h * scale)))
    target_h_mm = target_width_mm * (h / w)

    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    out = cv2.resize(gray, (target_w_px, target_h_px), interpolation=interp)

    if max(target_w_px, target_h_px) > 12000:
        warnings.append("Ukuran piksel sangat besar — pertimbangkan turunkan DPI agar file tak berat di EZCAD2.")

    # Simpan PNG grayscale dengan metadata DPI.
    pil = Image.fromarray(out, mode="L")
    pil.save(png_path, dpi=(dpi, dpi))
    pil.save(prev_after)  # preview after = hasil grayscale

    return RasterResult(
        png_path=png_path,
        preview_after=prev_after,
        preview_before=prev_before,
        size_mm=(target_width_mm, target_h_mm),
        px=(target_w_px, target_h_px),
        dpi=dpi,
        warnings=warnings,
    )
