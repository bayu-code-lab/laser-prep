"""Self-check end-to-end untuk Laser Prep.

Memanggil fungsi endpoint app.process() LANGSUNG (tanpa server, tanpa httpx, tanpa pytest)
supaya wiring parameter di app.py ikut teruji — bukan cuma fungsi di prep/.

Jalankan lewat ./check.sh — berkas ini cuma satu dari empat kumpulan cek, dan
menjalankannya sendirian melewatkan cek unit di prep/:

    docker compose run --rm --no-deps laser-prep ./check.sh
"""
from __future__ import annotations
import io
import json
import os
import shutil
import zipfile

import cv2
import ezdxf
import numpy as np
from PIL import Image
from fastapi import UploadFile, HTTPException

import app as appmod

SID = "0" * 32  # sid tetap supaya path hasil bisa ditebak; lolos sanitasi hex di app.py


def _png_bytes(arr: np.ndarray) -> io.BytesIO:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _upload(name: str, buf: io.BytesIO) -> UploadFile:
    return UploadFile(filename=name, file=buf)


def _call_resp(**kwargs):
    """Panggil endpoint process() dengan default lengkap; kwargs menimpa yang perlu.

    Mengembalikan OBJEK RESPONS (bukan dict) supaya status_code ikut bisa
    diperiksa — dipakai saat sebuah cek perlu memastikan kode status, bukan
    cuma isi body-nya.
    """
    args = dict(
        lp_sid=SID, job="grayscale", width_mm=20.0, height_mm=0.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
        mirror=False, autotrim=True, rotate=0, reset=True,
        scale_passthrough=False,
    )
    args.update(kwargs)
    # process() sengaja SINKRON (bukan async): kerjanya CPU murni lewat
    # cv2/vtracer/PIL, dan endpoint sync ditaruh FastAPI di threadpool sehingga
    # server tetap melayani permintaan lain — termasuk /out/... untuk pratinjau
    # berkas batch yang sudah selesai — selagi satu berkas diproses.
    return appmod.process(**args)


def _call(**kwargs) -> dict:
    """Sama seperti _call_resp, tapi langsung kembalikan body yang sudah di-parse —
    dipakai mayoritas cek yang tak peduli status_code."""
    return json.loads(_call_resp(**kwargs).body)


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


def check_svg_teks_hidup() -> None:
    """SVG ber-<text> harus DIPERINGATKAN, bukan diam-diam kehilangan tulisannya.

    svg2paths2 cuma membaca path & bentuk dasar. Tanpa peringatan ini operator
    menerima DXF tanpa tulisan pelanggan dan baru tahu setelah barang terukir.
    """
    tanpa = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
             '<path d="M1,1 L9,1 L9,9 L1,9 Z"/></svg>')
    dengan = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
              '<path d="M1,1 L9,1 L9,9 L1,9 Z"/><text x="2" y="5">Budi</text></svg>')

    d = _call(file=_upload("t.svg", io.BytesIO(dengan.encode())), job="vector", width_mm=30.0)
    assert d["ok"], d
    assert any("teks hidup" in w.lower() for w in d["warnings"]), \
        f"SVG ber-teks harus diperingatkan: {d['warnings']}"

    # Dan JANGAN diperingatkan saat tak ada teks: peringatan yang muncul di setiap
    # berkas melatih operator mengabaikan seluruh kolom peringatan.
    d = _call(file=_upload("p.svg", io.BytesIO(tanpa.encode())), job="vector", width_mm=30.0)
    assert d["ok"], d
    assert not any("teks hidup" in w.lower() for w in d["warnings"]), d["warnings"]


def check_state() -> None:
    """Preset & lensa bertahan di server, dan titipan raksasa ditolak."""
    asli = os.path.exists(appmod.STATE_PATH)
    cadangan = None
    if asli:
        with open(appmod.STATE_PATH, encoding="utf-8") as f:
            cadangan = f.read()
    try:
        os.path.exists(appmod.STATE_PATH) and os.remove(appmod.STATE_PATH)
        # Belum ada berkasnya: kosong, bukan galat — alat baru dipasang.
        assert json.loads(appmod.baca_state().body) == {}, "state kosong harus {}"

        isi = {"presets": {"kaca": {"job": "vector", "width_mm": "40"}},
               "lensa": [{"nama": "F254", "w": 175, "h": 175}], "lensaSel": 0}
        appmod.tulis_state(state=isi)
        assert json.loads(appmod.baca_state().body) == isi, "state tidak bertahan"

        # Berkas rusak tidak boleh mematikan alat: preset hilang, kemampuan
        # memproses berkas tidak. Tracebacknya memang dicetak — baca_state()
        # mengirimnya ke log server supaya kerusakan state.json bisa dilacak,
        # yang dilarang cuma menggagalkan permintaannya. Lihat catatan flush di
        # check_galat_tanpa_path_internal.
        print("  (traceback berikut disengaja — lihat check_state)", flush=True)
        with open(appmod.STATE_PATH, "w", encoding="utf-8") as f:
            f.write("{bukan json")
        assert json.loads(appmod.baca_state().body) == {}, "state rusak harus jatuh ke {}"

        # Dua simpan berbarengan tak boleh merusak berkasnya. Satu aksi operator
        # memang memicu dua simpan berurutan (preset lalu lensa) dan FastAPI
        # melayani keduanya di threadpool sekaligus — versi pertama endpoint ini
        # memakai satu nama .tmp tetap, dan state.json langsung rusak saat dicoba
        # di browser sungguhan.
        import threading
        mulai = threading.Barrier(6)

        def tulis(i: int) -> None:
            mulai.wait()
            appmod.tulis_state(state={"presets": {f"p{i}": {"width_mm": str(i)}}})

        utas = [threading.Thread(target=tulis, args=(i,)) for i in range(6)]
        for t in utas:
            t.start()
        for t in utas:
            t.join()
        hasil = json.loads(appmod.baca_state().body)
        assert hasil != {}, "state kosong setelah simpan berbarengan — berkasnya rusak"
        assert list(hasil["presets"])[0].startswith("p"), hasil
        # Tak boleh ada .tmp yatim tertinggal.
        sisa = [n for n in os.listdir(appmod.BASE) if n.startswith("state.json.")]
        assert not sisa, f"berkas sementara tertinggal: {sisa}"

        # Endpoint tanpa autentikasi tak boleh jadi jalan menulis berkas sebesar apa pun.
        try:
            appmod.tulis_state(state={"x": "y" * (appmod.STATE_MAX + 1)})
            raise AssertionError("state kegedean harus ditolak")
        except HTTPException as e:
            assert e.status_code == 413, e.status_code
    finally:
        if cadangan is None:
            os.path.exists(appmod.STATE_PATH) and os.remove(appmod.STATE_PATH)
        else:
            with open(appmod.STATE_PATH, "w", encoding="utf-8") as f:
                f.write(cadangan)


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
    # Fixture raster (l.png) -> app.py merutekan ke process_raster_logo. Jalur
    # SVG asli (process_svg_input) punya risiko regresi berbeda dan dicek
    # terpisah oleh check_rotate_svg.
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


def check_rotate_svg() -> None:
    """process_svg_input: rotate harus diterapkan SEBELUM fit_polylines, persis
    seperti process_raster_logo — kalau tidak, target ukuran ditafsirkan dalam
    orientasi SEBELUM putaran, bukan orientasi hasil akhir."""
    # Sumber SVG potret 1:2 (viewBox 10x20), path persegi panjang mengisi penuh.
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">'
           '<path d="M0,0 L10,0 L10,20 L0,20 Z"/></svg>')
    size = {}
    for deg in (0, 90):
        d = _call(file=_upload("p.svg", io.BytesIO(svg.encode())), job="vector",
                  width_mm=40.0, height_mm=20.0, rotate=deg)
        assert d["ok"], d
        x0, y0, x1, y1 = _dxf_bbox(_out_path(d["downloads"][0]["url"]))
        size[deg] = (x1 - x0, y1 - y0)
    # 0°: sumber tetap potret 1:2, target 40x20 -> tinggi yang membatasi -> 10x20.
    w0, h0 = size[0]
    assert abs(w0 - 10.0) < 0.5 and abs(h0 - 20.0) < 0.5, f"0°: {size[0]}"
    # 90°: sumber jadi lanskap 2:1, target 40x20 -> lebar yang membatasi -> 40x20.
    w90, h90 = size[90]
    assert abs(w90 - 40.0) < 0.5 and abs(h90 - 20.0) < 0.5, f"90°: {size[90]}"


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


def check_rotate_density() -> None:
    """Kepadatan titik pasca-putar: keputusan "perbesar lalu sampling ulang" harus
    memakai sisi yang benar-benar jadi LEBAR setelah rotate_polylines, bukan lebar
    sebelum diputar. Elips lanskap ~7:1: lebar pra-putar sudah ~pas target (tak
    perlu sampling ulang), tapi setelah diputar 90° yang jadi lebar adalah sisi
    PENDEKnya -- fit_polylines membesarkannya besar-besaran. Kalau keputusan
    sampling-ulang tetap memakai lebar pra-putar, pembesaran itu terjadi TANPA
    titik tambahan (poligon kasar) -- persis kelas kegagalan yang sudah ditutup
    check_frame_drop_density, dibuka lagi oleh task Putar."""
    img = np.full((900, 900), 255, np.uint8)
    cv2.ellipse(img, (450, 450), (400, 60), 0, 0, 360, 0, -1)
    d = _call(file=_upload("e.png", _png_bytes(img)), job="vector", width_mm=40.0, rotate=90)
    assert d["ok"], d
    doc = ezdxf.readfile(_out_path(d["downloads"][0]["url"]))
    n = max(len(e.get_points("xy")) for e in doc.modelspace().query("LWPOLYLINE"))
    assert n >= 1000, (
        f"kontur terbesar cuma {n} titik setelah putar 90° -- elips lanskap jadi "
        "poligon kasar (perbesaran dihitung dari sisi sebelum diputar, bukan sesudah)"
    )


def check_batch_reset() -> None:
    """File kedua dalam batch (reset=False) tidak boleh menghapus hasil file pertama."""
    arr = np.full((100, 100), 60, np.uint8)
    d1 = _call(file=_upload("satu.png", _png_bytes(arr)), reset=True, autotrim=False)
    assert d1["ok"], d1
    p1 = _out_path(d1["downloads"][0]["url"])
    assert os.path.exists(p1), p1
    d2 = _call(file=_upload("dua.png", _png_bytes(arr)), reset=False, autotrim=False)
    assert d2["ok"], d2
    p2 = _out_path(d2["downloads"][0]["url"])
    assert p1 != p2, "nama hasil bertabrakan — _safe_stem seharusnya membedakannya"
    assert os.path.exists(p1), "hasil file pertama terhapus oleh file kedua"
    assert os.path.exists(p2), p2


def check_batch_budget() -> None:
    """Ruang habis: file berikutnya ditolak dengan pesan, hasil lama tetap utuh."""
    arr = np.full((100, 100), 60, np.uint8)
    d1 = _call(file=_upload("a.png", _png_bytes(arr)), reset=True, autotrim=False)
    assert d1["ok"], d1
    p1 = _out_path(d1["downloads"][0]["url"])
    asli = appmod.BATCH_BUDGET
    try:
        appmod.BATCH_BUDGET = 1     # apa pun yang sudah ada pasti sudah melewatinya
        resp2 = _call_resp(file=_upload("b.png", _png_bytes(arr)), reset=False, autotrim=False)
    finally:
        appmod.BATCH_BUDGET = asli
    # Disengaja 200, bukan 400/500: ruang habis adalah kondisi yang diharapkan,
    # bukan kesalahan server — jangan "diperbaiki" jadi kode status galat.
    assert resp2.status_code == 200, resp2.status_code
    d2 = json.loads(resp2.body)
    assert not d2["ok"], "file kedua seharusnya ditolak saat ruang habis"
    assert "penuh" in d2["error"].lower(), d2["error"]
    assert os.path.exists(p1), "hasil yang sudah ada tidak boleh ikut hilang"


def check_zip() -> None:
    """ZIP memuat tepat berkas yang diminta; nama berbahaya ditolak."""
    arr = np.full((100, 100), 60, np.uint8)
    d1 = _call(file=_upload("a.png", _png_bytes(arr)), reset=True, autotrim=False)
    d2 = _call(file=_upload("b.png", _png_bytes(arr)), reset=False, autotrim=False)
    assert d1["ok"] and d2["ok"], (d1, d2)
    n1 = os.path.basename(d1["downloads"][0]["url"].split("?")[0])
    n2 = os.path.basename(d2["downloads"][0]["url"].split("?")[0])
    resp = appmod.zip_outputs(lp_sid=SID, names=[n1, n2])
    try:
        with zipfile.ZipFile(resp.path) as z:
            assert sorted(z.namelist()) == sorted([n1, n2]), z.namelist()
    finally:
        # BackgroundTask hanya berjalan di bawah ASGI; di sini kita bersihkan sendiri.
        os.remove(resp.path)
    # Tanpa penyaringan nama, "../app.py" akan mengemas berkas di luar folder sesi.
    for jahat in ["../app.py", "a/b.png", ".", "..", ""]:
        try:
            appmod.zip_outputs(lp_sid=SID, names=[jahat])
        except HTTPException as e:
            # Nilai kode status dipatok spec: 400 wajib persis, bukan sekadar "galat".
            assert e.status_code == 400, f"{jahat!r}: status {e.status_code}, harusnya 400"
        else:
            raise AssertionError(f"nama berbahaya lolos: {jahat!r}")


def _tulis_dxf(path: str, w: float, h: float) -> None:
    """DXF mm sederhana berukuran w x h, sengaja tidak di origin."""
    doc = ezdxf.new("R2010")
    doc.units = 4  # mm
    doc.modelspace().add_lwpolyline(
        [(5, 5), (5 + w, 5), (5 + w, 5 + h), (5, 5 + h)], close=True)
    doc.saveas(path)


def check_dxf_size() -> None:
    """DXF lewat apa adanya, TAPI ukurannya wajib dilaporkan."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "k.dxf")
        _tulis_dxf(p, 30.0, 12.0)
        with open(p, "rb") as f:
            buf = io.BytesIO(f.read())
    d2 = _call(file=_upload("k.dxf", buf), job="vector", width_mm=40.0)
    assert d2["ok"], d2
    assert d2["passthrough"] is True, d2
    assert d2["size_mm"] is not None, "ukuran DXF harus dilaporkan, bukan null"
    w, h = d2["size_mm"]
    assert abs(w - 30.0) < 0.05 and abs(h - 12.0) < 0.05, d2["size_mm"]
    # tanpa diminta, berkas TIDAK boleh diskalakan
    assert d2["downloads"][0]["url"].endswith(".dxf"), d2["downloads"]
    # mirror=False (default _call) -> TIDAK boleh ada peringatan cermin sama
    # sekali. Tanpa assert negatif ini, peringatan cermin bisa saja muncul
    # terus-menerus (bug kebalikannya) tanpa ada cek yang menangkapnya.
    assert not any("cermin" in x.lower() for x in d2["warnings"]), (
        f"peringatan cermin seharusnya TIDAK muncul saat mirror=False: {d2['warnings']}"
    )

    # Cermin diminta TANPA menekan skalakan: cermin tetap tidak diterapkan
    # (berkas tetap apa adanya), tapi operator wajib diberi tahu — bukan
    # menemukannya sendiri di EZCAD2.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.dxf")
        _tulis_dxf(p, 30.0, 12.0)
        with open(p, "rb") as f:
            buf = io.BytesIO(f.read())
    d3 = _call(file=_upload("m.dxf", buf), job="vector", width_mm=40.0,
               mirror=True, scale_passthrough=False)
    assert d3["ok"], d3
    assert d3["passthrough"] is True, d3
    assert any("cermin" in w.lower() for w in d3["warnings"]), (
        "mirror diminta tanpa skala harus memunculkan peringatan eksplisit: "
        f"{d3['warnings']}"
    )

    # Putaran diminta TANPA menekan skalakan: putaran tidak diterapkan (berkas
    # tetap apa adanya, app.py:235-239), tapi operator wajib diberi tahu --
    # nilai yang dipatok spec, belum ada penjaganya sebelum ini.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "r.dxf")
        _tulis_dxf(p, 30.0, 12.0)
        with open(p, "rb") as f:
            buf = io.BytesIO(f.read())
    d4 = _call(file=_upload("r.dxf", buf), job="vector", width_mm=40.0,
               rotate=90, scale_passthrough=False)
    assert d4["ok"], d4
    assert d4["passthrough"] is True, d4
    assert any("putaran" in w.lower() for w in d4["warnings"]), (
        "putaran diminta tanpa skala harus memunculkan peringatan eksplisit: "
        f"{d4['warnings']}"
    )
    # rotate=0 (default) -> TIDAK boleh ada peringatan putaran sama sekali.
    assert not any("putaran" in x.lower() for x in d2["warnings"]), (
        f"peringatan putaran seharusnya TIDAK muncul saat rotate=0: {d2['warnings']}"
    )


def check_plt_size() -> None:
    """PLT: 4000 x 2000 satuan plotter = 100 x 50 mm."""
    plt = b"IN;SP1;PU0,0;PD4000,0;PD4000,2000;PU;"
    d = _call(file=_upload("p.plt", io.BytesIO(plt)), job="vector", width_mm=40.0)
    assert d["ok"], d
    assert d["passthrough"] is True, d
    w, h = d["size_mm"]
    assert abs(w - 100.0) < 0.05 and abs(h - 50.0) < 0.05, d["size_mm"]


def check_file_tunggal_terlalu_besar() -> None:
    """Satu berkas raksasa harus ditolak dengan pesan, bukan menjebol tmpfs.

    BATCH_BUDGET sebelumnya cuma diperiksa SEBELUM menulis: folder kosong selalu
    lolos cek itu, lalu penyalinan berjalan sampai ruang habis dan mati dengan
    "No space left on device" -- persis kegagalan yang budget-nya dibuat untuk
    dihindari. Yang dijaga di sini: berkas yang lebih besar dari sisa ruang
    berhenti di tengah salin, dan potongannya TIDAK ditinggal di folder sesi.
    """
    _cleanup()
    besar = io.BytesIO(b"\x00" * 200_000)
    asli = appmod.BATCH_BUDGET
    try:
        appmod.BATCH_BUDGET = 50_000          # lebih kecil dari berkasnya
        resp = _call_resp(file=_upload("besar.png", besar), reset=True)
    finally:
        appmod.BATCH_BUDGET = asli
    # 200, sama seperti check_batch_budget: ruang habis adalah kondisi yang
    # diharapkan, bukan kesalahan server.
    assert resp.status_code == 200, resp.status_code
    d = json.loads(resp.body)
    assert not d["ok"], "berkas melebihi sisa ruang seharusnya ditolak"
    assert "besar" in d["error"].lower() or "penuh" in d["error"].lower(), d["error"]
    sisa = os.listdir(os.path.join(appmod.OUT_DIR, SID))
    assert sisa == [], f"potongan berkas gagal ditinggal di folder sesi: {sisa}"


def check_galat_tanpa_path_internal() -> None:
    """Pesan galat di layar operator tak boleh memuat path internal container.

    prep/passthrough.py sudah menerjemahkan galat ezdxf demi alasan ini; jalur
    raster/vektor memakai pustaka (cv2/PIL/vtracer) yang pesannya berbahasa
    Inggris dan kerap memuat path lengkap /app/_out/<sid>/... -- tak berguna buat
    operator, dan membocorkan id sesi ke layar.
    """
    # Dua traceback akan tercetak selama cek ini — itu memang yang diuji:
    # detailnya WAJIB masuk log server, yang dilarang cuma menampilkannya ke
    # layar operator. Bukan tanda cek-nya gagal.
    # flush: traceback keluar lewat stderr yang tak berbuffer, catatan ini lewat
    # stdout yang berbuffer — tanpa flush ia muncul SESUDAH traceback yang
    # hendak dijelaskannya.
    print("  (dua traceback berikut disengaja — lihat check_galat_tanpa_path_internal)",
          flush=True)
    arr = np.full((60, 60), 60, np.uint8)
    bocor = f"cannot write {os.path.join(appmod.OUT_DIR, SID, 'x.png')}"
    asli = appmod.process_photo
    try:
        def meledak(*a, **k):
            raise OSError(bocor)
        appmod.process_photo = meledak
        resp = _call_resp(file=_upload("t.png", _png_bytes(arr)))
    finally:
        appmod.process_photo = asli
    assert resp.status_code == 500, resp.status_code
    pesan = json.loads(resp.body)["error"]
    assert appmod.OUT_DIR not in pesan and SID not in pesan, f"path internal bocor: {pesan}"

    # Sisi sebaliknya: galat yang DIBUAT alat ini sendiri sudah berbahasa
    # Indonesia dan bebas path -- jangan ikut diganti pesan generik, operator
    # kehilangan satu-satunya petunjuk yang berguna.
    d = _call(file=_upload("rusak.png", io.BytesIO(b"bukan gambar sama sekali")))
    assert not d["ok"], d
    assert "gagal membaca gambar" in d["error"].lower(), d["error"]


def check_remove_bg() -> None:
    """Hapus background: latar seragam jadi putih, subjek tetap utuh."""
    img = np.full((200, 200, 3), (60, 90, 200), np.uint8)   # latar seragam
    img[70:130, 70:130] = (20, 20, 20)                      # subjek gelap di tengah
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    hasil = {}
    for on in (False, True):
        buf.seek(0)
        d = _call(file=_upload("bg.png", io.BytesIO(buf.getvalue())), remove_bg=on,
                  width_mm=50.8, dpi=100, autocontrast=False, autotrim=False)
        assert d["ok"], d
        hasil[on] = np.asarray(Image.open(_out_path(d["downloads"][0]["url"])))
        if on:
            assert any("background dihapus" in w.lower() for w in d["warnings"]), d["warnings"]
    # Sudut = latar. Dengan remove_bg ia wajib putih murni; tanpanya tidak.
    assert hasil[True][2, 2] >= 250, f"latar belum jadi putih: {hasil[True][2, 2]}"
    assert hasil[False][2, 2] < 250, f"fixture salah — latar sudah putih tanpa remove_bg"
    # Subjek TIDAK boleh ikut terhapus: itulah beda flood-fill dari segmentasi.
    assert hasil[True][100, 100] < 60, f"subjek ikut terhapus: {hasil[True][100, 100]}"


def check_gamma() -> None:
    """gamma > 1 mencerahkan, gamma < 1 menggelapkan, gamma = 1 tak mengubah apa pun."""
    arr = np.full((100, 100), 100, np.uint8)
    rata = {}
    for g in (0.5, 1.0, 2.0):
        d = _call(file=_upload("g.png", _png_bytes(arr)), gamma=g,
                  width_mm=25.4, dpi=100, autocontrast=False, autotrim=False)
        assert d["ok"], d
        rata[g] = float(np.asarray(Image.open(_out_path(d["downloads"][0]["url"]))).mean())
    assert rata[0.5] < rata[1.0] - 5, f"gamma 0.5 harus menggelapkan: {rata}"
    assert rata[2.0] > rata[1.0] + 5, f"gamma 2.0 harus mencerahkan: {rata}"
    assert abs(rata[1.0] - 100.0) < 2, f"gamma 1.0 harus netral: {rata}"


def check_clahe() -> None:
    """CLAHE menaikkan kontras LOKAL, dan itulah yang harus diukur.

    Std GLOBAL justru TURUN kena CLAHE (ia meratakan tanjakan besar sambil
    mengangkat tekstur halus) — mengukur std global akan menuduh CLAHE gagal
    padahal ia bekerja persis sebagaimana mestinya. Fixture: tanjakan lembut
    rentang penuh + tekstur pita tipis, kasus di mana autocontrast global tak
    bisa menolong apa-apa karena rentangnya memang sudah penuh.
    """
    y, x = np.mgrid[0:200, 0:200]
    arr = (x * 255 // 199).astype(np.uint8)
    arr = np.clip(arr.astype(np.int16) + ((y // 10) % 2) * 6, 0, 255).astype(np.uint8)

    def kontras_lokal(img: np.ndarray) -> float:
        f = img.astype(np.float32)
        return float((f - cv2.blur(f, (31, 31))).std())

    hasil = {}
    for on in (False, True):
        d = _call(file=_upload("c.png", _png_bytes(arr)), clahe=on, autocontrast=True,
                  width_mm=50.8, dpi=100, autotrim=False)
        assert d["ok"], d
        hasil[on] = kontras_lokal(np.asarray(Image.open(_out_path(d["downloads"][0]["url"]))))
    assert hasil[True] > hasil[False] * 1.5, f"CLAHE harus menaikkan kontras lokal: {hasil}"


def check_dxf_preview() -> None:
    """DXF/PLT dapat pratinjau gambar juga — kotak area kerja tanpa gambar cuma
    menjawab "muat atau tidak", bukan "ini benar berkasnya".

    Yang dipratinjau adalah berkas yang BENAR-BENAR dikirim: jalur apa adanya
    memratinjau berkas sumber, jalur terskala memratinjau hasil skalanya.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "v.dxf")
        _tulis_dxf(p, 30.0, 12.0)
        with open(p, "rb") as f:
            isi = f.read()

    for skala in (False, True):
        r = _call(file=_upload("v.dxf", io.BytesIO(isi)), job="vector",
                  width_mm=60.0, scale_passthrough=skala)
        assert r["ok"], r
        assert r["after"], f"DXF (skala={skala}) tanpa pratinjau: {r}"
        img = Image.open(_out_path(r["after"]))
        assert img.format == "PNG", img.format
        # Bukan kanvas kosong: persegi panjangnya harus benar-benar tergambar.
        assert np.asarray(img.convert("L")).min() < 100, "pratinjau DXF kosong"

    plt = b"IN;SP1;PU0,0;PD4000,0;PD4000,2000;PD0,2000;PD0,0;PU;"
    r = _call(file=_upload("v.plt", io.BytesIO(plt)), job="vector", width_mm=60.0)
    assert r["ok"], r
    assert r["after"], f"PLT tanpa pratinjau: {r}"
    assert np.asarray(Image.open(_out_path(r["after"])).convert("L")).min() < 100, \
        "pratinjau PLT kosong"


def check_dxf_scale() -> None:
    """Ditekan tombolnya: DXF diskalakan ke lebar target dan terpusat di (0,0)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.dxf")
        _tulis_dxf(p, 30.0, 12.0)
        with open(p, "rb") as f:
            buf = io.BytesIO(f.read())
    r = _call(file=_upload("s.dxf", buf), job="vector", width_mm=60.0,
              scale_passthrough=True)
    assert r["ok"], r
    assert r["passthrough"] is False, "hasil yang diskalakan bukan lagi passthrough"
    w, h = r["size_mm"]
    assert abs(w - 60.0) < 0.05 and abs(h - 24.0) < 0.05, r["size_mm"]
    x0, y0, x1, y1 = _dxf_bbox(_out_path(r["downloads"][0]["url"]))
    assert abs(x1 - x0 - 60.0) < 0.05, (x0, x1)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert abs(cx) < 0.01 and abs(cy) < 0.01, f"harus terpusat di (0,0): ({cx}, {cy})"


if __name__ == "__main__":
    try:
        check_invert_grayscale()
        check_preview_thumb()
        check_svg_preview_before()
        check_svg_teks_hidup()
        check_state()
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
        check_rotate_svg()
        check_rotate_density()
        check_batch_reset()
        check_batch_budget()
        check_zip()
        check_file_tunggal_terlalu_besar()
        check_galat_tanpa_path_internal()
        check_remove_bg()
        check_gamma()
        check_clahe()
        check_dxf_size()
        check_plt_size()
        check_dxf_scale()
        check_dxf_preview()
    finally:
        _cleanup()
    print("selfcheck ok")
