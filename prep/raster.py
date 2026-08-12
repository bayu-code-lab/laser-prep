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


def _remove_bg_color(bgr: np.ndarray, tol: int = 20) -> Tuple[np.ndarray, bool, str]:
    """Hapus background SERAGAM lewat flood-fill dari 4 sudut, jadikan putih.

    Beda dari rembg (segmentasi objek utama, sering ikut menghapus TEKS): cara ini
    cuma membuang area latar yang warnanya seragam & nyambung dari tepi. Semua yang
    tergambar — termasuk teks kecil — tetap aman. Gratis, offline, tanpa model.
    Cocok untuk logo/grafis berlatar polos; untuk foto berlatar ramai hasilnya minim.
    """
    h, w = bgr.shape[:2]
    mask = np.zeros((h + 2, w + 2), np.uint8)
    work = bgr.copy()
    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(
            work, mask, (sx, sy), (255, 255, 255),
            (tol, tol, tol), (tol, tol, tol), cv2.FLOODFILL_FIXED_RANGE,
        )
    filled = mask[1:h + 1, 1:w + 1].astype(bool)
    out = bgr.copy()
    out[filled] = (255, 255, 255)
    if not filled.any():
        return bgr, False, "Latar tidak seragam — tak ada yang dihapus (foto berlatar ramai)."
    return out, True, "Background dihapus (latar seragam) — teks tetap aman."


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
    prev_before = os.path.join(out_dir, f"{stem}_before.jpg")
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

    # preview 'before' cukup thumbnail JPEG — versi full-res cuma bikin sesi berat
    h, w = img.shape[:2]
    s = min(1.0, 900 / max(h, w))
    thumb = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1.0 else img
    cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])[1].tofile(prev_before)

    if remove_bg:
        img, ok, msg = _remove_bg_color(img)  # sudah berlatar putih
        warnings.append(msg)

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

    # Logo/grafis berlatar putih: buang abu-abu SANGAT tipis (bayangan/haze JPEG)
    # jadi putih murni — kalau tidak, ia ikut terukir & tampak "garis rusak".
    # Foto (nada kontinu, sedikit piksel putih) dilewati agar highlight tak jebol.
    if (gray >= 250).mean() > 0.35:
        gray[gray >= 210] = 255
        warnings.append("Latar & bayangan tipis dibersihkan jadi putih (grafis berlatar putih).")

    if invert:
        gray = cv2.bitwise_not(gray)

    # Penskalaan fisik: mm -> px pada DPI.
    h, w = gray.shape
    target_w_px = max(1, int(round(target_width_mm / 25.4 * dpi)))
    scale = target_w_px / w
    target_h_px = max(1, int(round(h * scale)))
    target_h_mm = target_width_mm * (h / w)

    # INTER_LINEAR saat memperbesar: INTER_CUBIC "overshoot" di tepi kontras tinggi,
    # bikin garis putus-putus/pecah di sekeliling bentuk. Linear halus, tanpa ringing.
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    out = cv2.resize(gray, (target_w_px, target_h_px), interpolation=interp)

    if scale > 1.05:
        warnings.append(
            f"Sumber {w}px diperbesar ke {target_w_px}px — detail tidak bertambah, "
            f"tepi bisa terlihat kasar. Untuk hasil tajam pakai gambar lebih besar "
            f"atau turunkan DPI (mis. {int(dpi * w / target_w_px)})."
        )

    if max(target_w_px, target_h_px) > 12000:
        warnings.append("Ukuran piksel sangat besar — pertimbangkan turunkan DPI agar file tak berat di EZCAD2.")

    # Simpan PNG grayscale dengan metadata DPI.
    Image.fromarray(out, mode="L").save(png_path, dpi=(dpi, dpi))

    return RasterResult(
        png_path=png_path,
        preview_after=png_path,  # hasilnya PNG grayscale itu sendiri — tak perlu salinan kedua
        preview_before=prev_before,
        size_mm=(target_width_mm, target_h_mm),
        px=(target_w_px, target_h_px),
        dpi=dpi,
        warnings=warnings,
    )
