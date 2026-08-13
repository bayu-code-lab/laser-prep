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

import cv2
import ezdxf
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
        lp_sid=SID, job="grayscale", width_mm=20.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
    )
    args.update(kwargs)
    return json.loads(asyncio.run(appmod.process(**args)).body)


def _out_path(url: str) -> str:
    return os.path.join(appmod.OUT_DIR, SID, os.path.basename(url.split("?")[0]))


def _cleanup() -> None:
    shutil.rmtree(os.path.join(appmod.OUT_DIR, SID), ignore_errors=True)


def _dxf_bbox(path: str) -> tuple:
    """(xmin, ymin, xmax, ymax) dari semua LWPOLYLINE dalam DXF."""
    doc = ezdxf.readfile(path)
    pts = [p for e in doc.modelspace().query("LWPOLYLINE") for p in e.get_points("xy")]
    assert pts, f"DXF tidak memuat polyline: {path}"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _framed_img() -> np.ndarray:
    """Bingkai persegi penuh-gambar + subjek jauh lebih kecil di dalamnya.

    Meniru logo hasil scan / screenshot berbingkai: _drop_frame_and_speckle akan
    membuang bingkainya, jadi skala harus dihitung ulang dari subjek yang tersisa.
    """
    img = np.full((600, 600), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (589, 589), 0, 6)
    cv2.circle(img, (300, 300), 120, 0, -1)
    return img


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


def check_preview_thumb() -> None:
    """bug #2: preview harus thumbnail; berkas download tetap resolusi penuh."""
    arr = np.full((1200, 1200), 128, np.uint8)
    arr[0:400, :] = 20
    d = _call(file=_upload("t.png", _png_bytes(arr)), width_mm=200.0, dpi=600)
    assert d["ok"], d
    for key in ("before", "after"):
        size = Image.open(_out_path(d[key])).size
        assert max(size) <= 900, f"preview '{key}' terlalu besar: {size}"
    # Preview hasil harus lossless: operator menilai gradasi & banding dari situ,
    # artefak JPEG akan tampak seperti cacat yang sebenarnya tak ada di berkas ukir.
    assert Image.open(_out_path(d["after"])).format == "PNG", d["after"]
    full = Image.open(_out_path(d["downloads"][0]["url"])).size
    assert full[0] == 4724, f"berkas download harus resolusi penuh: {full}"


def check_svg_preview_before() -> None:
    """bug #6: untuk input SVG, panel 'sebelum' harus menunjuk SVG sumber, bukan hasil render."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<path d="M1,1 L9,1 L9,9 L1,9 Z"/></svg>')
    d = _call(file=_upload("s.svg", io.BytesIO(svg.encode())), job="vector", width_mm=30.0)
    assert d["ok"], d
    assert ".svg" in d["before"], f"'sebelum' harus berkas SVG sumber: {d['before']}"
    # bandingkan path di disk, bukan URL: keduanya dapat cache-buster '?v=' yang berbeda
    # sehingga string URL-nya selalu tampak beda meski menunjuk berkas yang sama.
    assert _out_path(d["before"]) != _out_path(d["after"]), d


def check_frame_drop_size() -> None:
    """(a): diminta 40 mm, DXF harus benar-benar 40 mm — dan laporan harus jujur."""
    d = _call(file=_upload("f.png", _png_bytes(_framed_img())), job="vector", width_mm=40.0)
    assert d["ok"], d
    x0, _, x1, _ = _dxf_bbox(_out_path(d["downloads"][0]["url"]))
    nyata = x1 - x0
    assert abs(nyata - 40.0) < 0.5, f"lebar DXF nyata {nyata:.2f} mm, diminta 40"
    assert abs(d["size_mm"][0] - nyata) < 0.5, f"dilapor {d['size_mm'][0]}, nyata {nyata:.2f}"


def check_dxf_centered() -> None:
    """(b): geometri DXF berpusat di (0,0) supaya mendarat di tengah field EZCAD2."""
    img = np.full((400, 400), 255, np.uint8)
    cv2.circle(img, (200, 200), 120, 0, -1)
    d = _call(file=_upload("c.png", _png_bytes(img)), job="vector", width_mm=30.0)
    assert d["ok"], d
    x0, y0, x1, y1 = _dxf_bbox(_out_path(d["downloads"][0]["url"]))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert abs(cx) < 0.01 and abs(cy) < 0.01, f"pusat DXF ({cx:.3f}, {cy:.3f}), harusnya (0,0)"


if __name__ == "__main__":
    try:
        check_invert_grayscale()
        check_preview_thumb()
        check_svg_preview_before()
        check_frame_drop_size()
        check_dxf_centered()
    finally:
        _cleanup()
    print("selfcheck ok")
