"""Self-check end-to-end untuk Laser Prep.

Memanggil fungsi endpoint app.process() LANGSUNG (tanpa server, tanpa httpx, tanpa pytest)
supaya wiring parameter di app.py ikut teruji — bukan cuma fungsi di prep/.

Jalankan:  docker compose run --rm --no-deps laser-prep python selfcheck.py
"""
from __future__ import annotations
import asyncio
import io
import json
import os
import shutil

import numpy as np
from PIL import Image
from fastapi import UploadFile

import app as appmod

SID = "0" * 32  # sid tetap supaya path hasil bisa ditebak; lolos sanitasi hex di app.py


def _png_bytes(arr: np.ndarray) -> io.BytesIO:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _upload(name: str, buf: io.BytesIO) -> UploadFile:
    return UploadFile(filename=name, file=buf)


def _call(**kwargs) -> dict:
    """Panggil endpoint process() dengan default lengkap; kwargs menimpa yang perlu."""
    args = dict(
        lp_sid=SID, job="uv", width_mm=20.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
    )
    args.update(kwargs)
    return json.loads(asyncio.run(appmod.process(**args)).body)


def _out_path(url: str) -> str:
    return os.path.join(appmod.OUT_DIR, SID, os.path.basename(url.split("?")[0]))


def _cleanup() -> None:
    shutil.rmtree(os.path.join(appmod.OUT_DIR, SID), ignore_errors=True)


def _patch_img() -> np.ndarray:
    """Gambar gelap dengan satu bercak terang — sengaja tidak simetris supaya
    rata-rata pikselnya berbalik jelas saat di-invert."""
    arr = np.full((200, 200), 40, np.uint8)
    arr[80:120, 80:120] = 200
    return arr


def check_invert_grayscale() -> None:
    """bug #1: checkbox 'Balik (negatif)' harus benar-benar sampai ke process_photo."""
    arr = _patch_img()
    means = {}
    for inv in (False, True):
        d = _call(file=_upload("t.png", _png_bytes(arr)), invert=inv)
        assert d["ok"], d
        png = _out_path(d["downloads"][0]["url"])
        means[inv] = float(np.asarray(Image.open(png)).mean())
    assert means[False] < 60, f"tanpa invert seharusnya gelap: {means}"
    assert means[True] > 200, f"dengan invert seharusnya terang: {means}"


if __name__ == "__main__":
    try:
        check_invert_grayscale()
    finally:
        _cleanup()
    print("selfcheck ok")
