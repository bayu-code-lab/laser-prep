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
    points_per_mm: float = 12.0,
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
            # 12 titik/mm dipilih dari simpangan tali busur (sagitta ≈ c²/8r), bukan
            # dari selera: menjaga simpangan <= 0.01 mm sampai radius 0.1 mm butuh
            # ~11 titik/mm. Pada lengkung besar ini jauh berlebih dan itu tak apa —
            # ongkosnya cuma ukuran berkas, sementara kekurangannya keluar sebagai
            # sudut kasat mata pada sudut huruf kecil.
            #
            # Batas atas 20000 (bukan 6000): pada 12 titik/mm, 6000 mulai menggigit
            # di kontur sepanjang 500 mm — dan kontur sepanjang itu justru khas
            # untuk teks kecil yang berkelok, kasus yang paling butuh kerapatan.
            # Batas ini pengaman runaway, bukan pembatas kualitas.
            n = int(length_mm * points_per_mm)
            n = max(8, min(n, 20000))
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


def _bbox(polylines: List[Polyline]) -> Tuple[float, float, float, float] | None:
    """(xmin, ymin, xmax, ymax) dari semua titik; None bila tak ada titik sama sekali."""
    xs = [p[0] for pts, _ in polylines for p in pts]
    ys = [p[1] for pts, _ in polylines for p in pts]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def fit_polylines(
    polylines: List[Polyline],
    target_width_mm: float,
    target_height_mm: float | None = None,
) -> Tuple[List[Polyline], Tuple[float, float]]:
    """Skalakan polyline agar bbox-nya pas target; kembalikan (polyline, ukuran sebenarnya).

    Rasio selalu dijaga. Tanpa target_height_mm: bbox dibuat selebar target_width_mm.
    Dengan target_height_mm: hasilnya MUAT di dalam kotak — satu sisi pas, sisi lain
    lebih kecil atau sama. Hasil dinormalkan ke pojok (0,0); pemusatan untuk EZCAD2
    dilakukan belakangan di write_dxf, bukan di sini.
    """
    box = _bbox(polylines)
    if box is None:
        return [], (0.0, 0.0)
    xmin, ymin, xmax, ymax = box
    src_w, src_h = xmax - xmin, ymax - ymin

    scale = target_width_mm / src_w if src_w > 0 else None
    if target_height_mm and src_h > 0:
        s = target_height_mm / src_h
        scale = s if scale is None else min(scale, s)
    if not scale or scale <= 0:
        # Bentuk merosot (garis lurus sempurna / satu titik): tak ada yang bisa
        # diskalakan, tapi janji "dinormalkan ke pojok (0,0)" tetap ditepati.
        out = [([(x - xmin, y - ymin) for x, y in pts], closed) for pts, closed in polylines]
        return out, (src_w, src_h)

    out = [
        ([((x - xmin) * scale, (y - ymin) * scale) for x, y in pts], closed)
        for pts, closed in polylines
    ]
    return out, (src_w * scale, src_h * scale)


def mirror_polylines(polylines: List[Polyline], width_mm: float) -> List[Polyline]:
    """Cermin horizontal: x -> width_mm - x. Urutan titik & status tertutup dipertahankan."""
    return [([(width_mm - x, y) for x, y in pts], closed) for pts, closed in polylines]


# Putar searah jarum jam DI LAYAR. Sumbu Y di modul ini ke atas, jadi titik di
# atas (0, 1) harus mendarat di kanan (1, 0) untuk 90°.
_ROT = {
    90: lambda x, y: (y, -x),
    180: lambda x, y: (-x, -y),
    270: lambda x, y: (-y, x),
}


def rotate_polylines(polylines: List[Polyline], deg: int) -> List[Polyline]:
    """Putar polyline 0/90/180/270 derajat searah jarum jam (dilihat di layar).

    Hasilnya sengaja TIDAK dinormalkan ke pojok (0,0) — pemanggil selalu
    meneruskannya ke fit_polylines, yang memang bertugas menormalkan. Derajat di
    luar 0/90/180/270 diperlakukan sebagai 0.
    """
    f = _ROT.get(int(deg))
    if f is None:
        return polylines
    return [([f(x, y) for x, y in pts], closed) for pts, closed in polylines]


def write_dxf(polylines: List[Polyline], out_path: str) -> None:
    """Tulis polyline (mm) ke DXF R2010, satuan milimeter, siap import EZCAD2.

    Geometri digeser agar berpusat di (0,0): field EZCAD2 berpusat di origin, jadi
    objek yang berpusat di origin langsung mendarat di tengah tanpa ditengahkan manual.
    """
    doc = ezdxf.new("R2010")
    doc.units = ezunits.MM  # $INSUNITS = 4 (mm)
    msp = doc.modelspace()
    box = _bbox(polylines)
    cx, cy = (0.0, 0.0) if box is None else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    for pts, closed in polylines:
        msp.add_lwpolyline(
            [(x - cx, y - cy) for x, y in pts], close=closed, dxfattribs={"layer": "ENGRAVE"}
        )
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


if __name__ == "__main__":
    # self-check: fit, fit-to-box, mirror, dan pemusatan DXF
    import os
    import tempfile

    # persegi panjang 20x10 mm, sengaja tidak di origin
    sq = ([(10.0, 10.0), (30.0, 10.0), (30.0, 20.0), (10.0, 20.0)], True)

    fitted, size = fit_polylines([sq], 40.0)
    assert abs(size[0] - 40.0) < 1e-6 and abs(size[1] - 20.0) < 1e-6, size
    assert min(p[0] for p in fitted[0][0]) == 0.0, fitted[0][0]
    assert min(p[1] for p in fitted[0][0]) == 0.0, fitted[0][0]

    # tinggi membatasi: 40 lebar mustahil kalau tinggi maks cuma 5
    boxed, size = fit_polylines([sq], 40.0, 5.0)
    assert abs(size[0] - 10.0) < 1e-6 and abs(size[1] - 5.0) < 1e-6, size

    # lebar membatasi: tinggi maks longgar, hasil sama dengan tanpa kotak
    boxed, size = fit_polylines([sq], 40.0, 999.0)
    assert abs(size[0] - 40.0) < 1e-6 and abs(size[1] - 20.0) < 1e-6, size

    assert fit_polylines([], 40.0) == ([], (0.0, 0.0))

    # bentuk merosot: garis vertikal sempurna, tak ada lebar untuk diskalakan
    vline = ([(5.0, 2.0), (5.0, 12.0)], False)
    degen, size = fit_polylines([vline], 40.0)
    assert size == (0.0, 10.0), size
    assert degen[0][0] == [(0.0, 0.0), (0.0, 10.0)], degen[0][0]

    m = mirror_polylines([sq], 40.0)
    assert [p[0] for p in m[0][0]] == [30.0, 10.0, 10.0, 30.0], m[0][0]
    assert [p[1] for p in m[0][0]] == [10.0, 10.0, 20.0, 20.0], m[0][0]
    assert m[0][1] is True, m[0][1]

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.dxf")
        write_dxf([sq], path)
        doc = ezdxf.readfile(path)
        pts = [p for e in doc.modelspace().query("LWPOLYLINE") for p in e.get_points("xy")]
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        assert abs(cx) < 1e-6 and abs(cy) < 1e-6, f"DXF harus berpusat di (0,0), dapat ({cx}, {cy})"
        write_dxf([], os.path.join(d, "kosong.dxf"))  # daftar kosong tetap sah

    # putar: SEARAH JARUM JAM sebagaimana terlihat di layar.
    # Koordinat di sini Y-ke-ATAS, jadi "atas" = +y. Garis yang menunjuk ke ATAS
    # harus menunjuk ke KANAN setelah diputar 90°.
    up = ([(0.0, 0.0), (0.0, 10.0)], False)
    assert rotate_polylines([up], 90)[0][0] == [(0.0, 0.0), (10.0, 0.0)]
    assert rotate_polylines([up], 180)[0][0] == [(0.0, 0.0), (0.0, -10.0)]
    assert rotate_polylines([up], 270)[0][0] == [(0.0, 0.0), (-10.0, 0.0)]
    assert rotate_polylines([up], 90)[0][1] is False        # status tertutup terjaga
    assert rotate_polylines([up], 0) == [up]                # 0 = tanpa perubahan
    assert rotate_polylines([up], 45) == [up]               # derajat tak sah = 0
    assert rotate_polylines([], 90) == []

    # Kerapatan sampling: yang diperiksa BUKAN "jumlah titiknya naik", melainkan
    # simpangan geometris sebenarnya — seberapa jauh tali busur polyline memotong
    # ke dalam kurva aslinya (sagitta). Itulah yang keluar sebagai sudut kasat mata
    # saat diukir. Radius 0.3 mm dipilih karena mewakili kasus terburuk yang nyata:
    # sudut huruf kecil / serif. Pada lengkung besar simpangan selalu sepele, jadi
    # menguji lingkaran 20 mm tidak akan pernah menangkap regresi apa pun.
    with tempfile.TemporaryDirectory() as d:
        svg = os.path.join(d, "c.svg")
        with open(svg, "w") as fh:
            fh.write(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<path d="M 100,0 A 100,100 0 1 0 99.99,0 Z"/></svg>'
            )
        diameter_mm = 0.6                       # radius 0.3 mm
        polys, size = svg_to_polylines_mm(svg, target_width_mm=diameter_mm)
        assert abs(size[0] - diameter_mm) < 1e-6, size
        r = diameter_mm / 2
        cx = cy = r                             # bbox digeser ke origin oleh tx()
        # Simpangan ada di TENGAH tali busur, bukan di titik-titiknya: tiap titik
        # hasil sampling duduk persis di atas kurva, jadi mengukur jaraknya dari
        # pusat selalu memberi r dan tidak menguji apa pun.
        pts = polys[0][0]
        sagitta = max(
            r - math.hypot((a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy)
            for a, b in zip(pts, pts[1:])
        )
        assert sagitta < 0.01, (
            f"simpangan tali busur {sagitta * 1000:.1f} µm pada radius {r} mm — "
            f"di atas 10 µm, sudutnya akan terbaca saat diukir"
        )


    print("ok")
