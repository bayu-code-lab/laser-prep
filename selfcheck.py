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
        lp_sid=SID, job="grayscale", width_mm=20.0, height_mm=0.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
        mirror=False, autotrim=True, rotate=0,
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


def _dxf_centroid(path: str) -> tuple:
    """Rata-rata posisi semua verteks LWPOLYLINE. Cukup untuk menjawab
    'ke arah mana bentuknya berputar' — bbox tidak bisa, karena bbox bentuk L
    tetap persegi ke arah mana pun ia diputar."""
    doc = ezdxf.readfile(path)
    pts = [p for e in doc.modelspace().query("LWPOLYLINE") for p in e.get_points("xy")]
    assert pts, f"DXF tidak memuat polyline: {path}"
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


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
        d = _call(file=_upload("t.png", _png_bytes(arr)), invert=inv, autotrim=False)
        assert d["ok"], d
        png = _out_path(d["downloads"][0]["url"])
        means[inv] = float(np.asarray(Image.open(png)).mean())
    assert means[False] < 60, f"tanpa invert seharusnya gelap: {means}"
    assert means[True] > 200, f"dengan invert seharusnya terang: {means}"


def check_preview_thumb() -> None:
    """bug #2: preview harus thumbnail; berkas download tetap resolusi penuh."""
    arr = np.full((1200, 1200), 128, np.uint8)
    arr[0:400, :] = 20
    d = _call(file=_upload("t.png", _png_bytes(arr)), width_mm=200.0, dpi=600, autotrim=False)
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


def check_fit_box() -> None:
    """(e): minta 40x20 pada gambar persegi -> muat di kotak, rasio terjaga."""
    # Vektor: lingkaran pada kanvas persegi, tinggi yang membatasi.
    img = np.full((400, 400), 255, np.uint8)
    cv2.circle(img, (200, 200), 150, 0, -1)
    d = _call(file=_upload("b.png", _png_bytes(img)), job="vector", width_mm=40.0, height_mm=20.0)
    assert d["ok"], d
    x0, y0, x1, y1 = _dxf_bbox(_out_path(d["downloads"][0]["url"]))
    w, h = x1 - x0, y1 - y0
    assert w <= 40.05 and h <= 20.05, f"vektor keluar kotak: {w:.2f} x {h:.2f}"
    assert abs(h - 20.0) < 0.5, f"sisi pembatas harus pas 20 mm, dapat {h:.2f}"
    assert abs(w - h) < 0.5, f"sumber persegi harus keluar persegi, bukan diregangkan: {w:.2f} x {h:.2f}"

    # Grayscale: gradien penuh-kanvas (tak ada margin polos, jadi bebas dari auto-trim).
    grad = np.tile(np.linspace(0, 255, 400).astype(np.uint8), (400, 1))
    d = _call(file=_upload("g.png", _png_bytes(grad)), width_mm=40.0, height_mm=20.0, dpi=100)
    assert d["ok"], d
    gw, gh = d["size_mm"]
    # Toleransi 0.2 mm: cabang grayscale membulatkan ke piksel utuh, jadi 20 mm @100 dpi
    # jatuh di 79 px = 20.07 mm. Batas yang lebih ketat akan gagal karena pembulatan,
    # bukan karena fit-to-box-nya salah.
    assert gw <= 40.2 and gh <= 20.2, f"grayscale keluar kotak: {gw} x {gh}"
    assert abs(gh - 20.0) < 0.3, f"sisi pembatas harus ≈20 mm, dapat {gh}"
    assert any("tinggi maks" in x.lower() for x in d["warnings"]), d["warnings"]
    assert abs(gw - gh) < 0.2, f"sumber persegi harus keluar persegi, bukan diregangkan: {gw} x {gh}"


def check_mirror() -> None:
    """(d): hasil mirror harus cerminan PERSIS dari hasil biasa, bukan sekadar berbeda."""
    # 300 px @ 76.2 mm @ 100 dpi -> tepat 300 px keluar, jadi resize = identitas
    # dan perbandingan piksel bebas dari galat pembulatan interpolasi.
    arr = np.full((200, 300), 200, np.uint8)
    arr[:, 0:60] = 30
    outs = {}
    for m in (False, True):
        d = _call(
            file=_upload("m.png", _png_bytes(arr)),
            width_mm=76.2, dpi=100, mirror=m, autocontrast=False, autotrim=False,
        )
        assert d["ok"], d
        outs[m] = np.asarray(Image.open(_out_path(d["downloads"][0]["url"])))
    assert outs[False].shape == (200, 300), outs[False].shape
    assert np.array_equal(outs[True], np.fliplr(outs[False])), "hasil mirror bukan cerminan"


def check_autotrim() -> None:
    """(c): margin polos dibuang sebelum penskalaan, jadi mm mengacu ke artwork."""
    arr = np.full((400, 400), 255, np.uint8)
    arr[150:250, 150:250] = 0          # artwork 100x100 di tengah kanvas 400x400
    hasil = {}
    for on in (True, False):
        d = _call(file=_upload("a.png", _png_bytes(arr)), width_mm=25.4, dpi=100, autotrim=on)
        assert d["ok"], d
        hasil[on] = np.asarray(Image.open(_out_path(d["downloads"][0]["url"]))).mean()
    assert hasil[True] < 20, f"terpangkas: isi harus memenuhi bingkai, rata-rata {hasil[True]:.1f}"
    assert hasil[False] > 150, f"tanpa trim: kanvas putih ikut, rata-rata {hasil[False]:.1f}"


def check_rotate_grayscale() -> None:
    """Putar 90/180/270 harus SEARAH JARUM JAM, dibandingkan piksel-demi-piksel."""
    # Sumber PERSEGI dengan sengaja: penskalaan menargetkan LEBAR, jadi sumber
    # non-persegi keluar dengan jumlah piksel berbeda setelah diputar dan
    # perbandingan piksel jadi mustahil. 300px @ 76.2mm @ 100dpi -> 300px,
    # sehingga resize jadi identitas dan tak ada galat interpolasi.
    arr = np.full((300, 300), 200, np.uint8)
    arr[0:50, :] = 30      # pita gelap di ATAS
    arr[:, 0:20] = 90      # pita kedua di KIRI -> tak simetris di dua sumbu,
                           # sehingga 90/180/270 saling terbedakan
    out = {}
    for deg in (0, 90, 180, 270):
        d = _call(file=_upload("r.png", _png_bytes(arr)), width_mm=76.2, dpi=100,
                  rotate=deg, autocontrast=False, autotrim=False)
        assert d["ok"], d
        out[deg] = np.asarray(Image.open(_out_path(d["downloads"][0]["url"])))
    assert out[0].shape == (300, 300), out[0].shape
    # np.rot90(k=-1) = searah jarum jam
    assert np.array_equal(out[90], np.rot90(out[0], k=-1)), "90° bukan searah jarum jam"
    assert np.array_equal(out[180], np.rot90(out[0], k=2)), "180° salah"
    assert np.array_equal(out[270], np.rot90(out[0], k=1)), "270° salah"


def check_rotate_size_swap() -> None:
    """Ukuran yang dilaporkan mengikuti hasil AKHIR: 90° menukar lebar dan tinggi."""
    arr = np.full((200, 400), 200, np.uint8)   # 400 lebar x 200 tinggi
    arr[0:40, :] = 30
    d0 = _call(file=_upload("s.png", _png_bytes(arr)), width_mm=40.0, height_mm=40.0,
               dpi=100, rotate=0, autocontrast=False, autotrim=False)
    d9 = _call(file=_upload("s.png", _png_bytes(arr)), width_mm=40.0, height_mm=40.0,
               dpi=100, rotate=90, autocontrast=False, autotrim=False)
    assert d0["ok"] and d9["ok"], (d0, d9)
    w0, h0 = d0["size_mm"]
    w9, h9 = d9["size_mm"]
    assert abs(w0 - 40.0) < 0.3 and abs(h0 - 20.0) < 0.3, d0["size_mm"]
    assert abs(w9 - h0) < 0.3 and abs(h9 - w0) < 0.3, (d0["size_mm"], d9["size_mm"])


def check_rotate_mirror_order() -> None:
    """Putar DULU, baru cermin. Untuk 90° urutan terbalik memberi hasil berbeda."""
    arr = np.full((300, 300), 200, np.uint8)
    arr[0:60, :] = 30      # atas
    arr[:, 0:30] = 90      # kiri
    d = _call(file=_upload("o.png", _png_bytes(arr)), width_mm=76.2, dpi=100,
              rotate=90, mirror=True, autocontrast=False, autotrim=False)
    assert d["ok"], d
    got = np.asarray(Image.open(_out_path(d["downloads"][0]["url"])))
    putar_lalu_cermin = np.fliplr(np.rot90(arr, k=-1))
    cermin_lalu_putar = np.rot90(np.fliplr(arr), k=-1)
    # Tanpa baris ini cek di bawah bisa lulus untuk kedua urutan dan tak
    # membuktikan apa-apa.
    assert not np.array_equal(putar_lalu_cermin, cermin_lalu_putar), \
        "fixture tidak membedakan urutan — perbaiki fixture-nya"
    assert np.array_equal(got, putar_lalu_cermin), \
        "urutan salah: cermin diterapkan sebelum putar"


def check_rotate_vector() -> None:
    """Mode Vektor memutar ke arah yang SAMA dengan Grayscale (searah jarum jam)."""
    # Bentuk L: batang tegak di kiri + kaki mendatar di bawah. Tak simetris,
    # jadi titik beratnya jauh dari pusat dan arah putaran terbaca.
    img = np.full((400, 400), 255, np.uint8)
    cv2.rectangle(img, (60, 60), (120, 340), 0, -1)
    cv2.rectangle(img, (60, 280), (340, 340), 0, -1)
    c = {}
    for deg in (0, 90):
        d = _call(file=_upload("l.png", _png_bytes(img)), job="vector",
                  width_mm=40.0, rotate=deg)
        assert d["ok"], d
        c[deg] = _dxf_centroid(_out_path(d["downloads"][0]["url"]))
    # DXF dipusatkan di (0,0), jadi titik berat yang jauh dari nol = bentuk
    # memang tak simetris. Tanpa ini, cek rotasi di bawah bisa lulus untuk
    # bentuk simetris apa pun.
    assert abs(c[0][0]) > 0.5 or abs(c[0][1]) > 0.5, f"fixture terlalu simetris: {c[0]}"
    # searah jarum jam: (x, y) -> (y, -x)
    assert abs(c[90][0] - c[0][1]) < 0.3 and abs(c[90][1] + c[0][0]) < 0.3, \
        f"arah putaran vektor salah: 0°={c[0]}, 90°={c[90]}"


def check_frame_drop_density() -> None:
    """(a lanjutan): subjek yang dibesarkan setelah bingkai dibuang harus tetap rapat
    titiknya — kalau tidak, lingkaran 40 mm keluar sebagai poligon kasar."""
    img = np.full((900, 900), 255, np.uint8)
    cv2.rectangle(img, (5, 5), (894, 894), 0, 5)   # bingkai penuh-gambar
    cv2.circle(img, (450, 450), 60, 0, -1)         # subjek kecil: ~13% lebar kanvas
    d = _call(file=_upload("d.png", _png_bytes(img)), job="vector", width_mm=40.0)
    assert d["ok"], d
    doc = ezdxf.readfile(_out_path(d["downloads"][0]["url"]))
    n = max(len(e.get_points("xy")) for e in doc.modelspace().query("LWPOLYLINE"))
    assert n >= 200, f"kontur terbesar cuma {n} titik — lingkaran 40 mm jadi poligon kasar"


if __name__ == "__main__":
    try:
        check_invert_grayscale()
        check_preview_thumb()
        check_svg_preview_before()
        check_frame_drop_size()
        check_dxf_centered()
        check_frame_drop_density()
        check_fit_box()
        check_mirror()
        check_autotrim()
        check_rotate_grayscale()
        check_rotate_size_swap()
        check_rotate_mirror_order()
        check_rotate_vector()
    finally:
        _cleanup()
    print("selfcheck ok")
