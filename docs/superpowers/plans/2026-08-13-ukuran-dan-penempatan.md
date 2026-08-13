# Ukuran & Penempatan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ukuran yang diminta operator harus sama dengan ukuran yang keluar dari mesin, dan geometrinya mendarat di tengah field EZCAD2 — plus mirror, batas tinggi, dan auto-trim margin.

**Architecture:** Bug ukuran, pemusatan DXF, dan fit-to-box pada cabang vektor adalah satu masalah — "skalakan dan tempatkan geometri sesuai target". Dua fungsi murni baru di `prep/geometry.py` (`fit_polylines`, `mirror_polylines`) melayani ketiganya, diuji sendiri lebih dulu sebagai unit sebelum di-wire. Pemusatan hanya terjadi di `write_dxf`, sehingga `render_preview` dan berkas SVG tetap memakai koordinat pojok-(0,0) yang sudah mereka asumsikan.

**Tech Stack:** Python 3.12, FastAPI, OpenCV (`opencv-python-headless`), Pillow, NumPy, vtracer, ezdxf, svgpathtools. Dijalankan lewat Docker Compose.

**Spec:** [docs/superpowers/specs/2026-08-13-ukuran-dan-penempatan-design.md](../specs/2026-08-13-ukuran-dan-penempatan-design.md)

## Global Constraints

- **Tanpa dependensi baru.** `requirements.txt` tidak boleh bertambah. Tidak ada pytest, tidak ada httpx. Cek memakai `assert` polos, mengikuti gaya `prep/vector.py`.
- **`cv2` tidak terpasang di host.** Semua perintah Python dijalankan di dalam container: `docker compose run --rm --no-deps laser-prep <perintah>`. Jalankan dari akar repo; satu run makan ~10–60 detik.
- **Bahasa.** Semua teks yang dilihat operator (label UI, hint, pesan error, warning) dan semua komentar/docstring ditulis dalam **Bahasa Indonesia**.
- **Nama mode yang berlaku, persis:** `Ke Vektor (DXF)` dan `Ke Grayscale (PNG)`. Nilai `job`: `"vector"` dan `"grayscale"`.
- **Pemusatan hanya di `write_dxf`.** Geometri internal tetap dimulai dari pojok (0,0). Jangan memusatkan di `fit_polylines`, `render_preview`, atau keluaran SVG.
- **Rasio aspek selalu dijaga.** Fit-to-box berarti MUAT DI DALAM kotak (`min()` dari kedua skala), bukan diregangkan.
- **Auto-trim menyala secara default**; `mirror` mati secara default; `height_mm` kosong berarti perilaku persis seperti sekarang.
- **Setiap cek baru wajib terbukti gagal** saat perbaikannya dibalikkan. Cek yang tidak bisa gagal bukan cek — buktikan, jangan asumsikan.
- `python -m prep.vector` dan `python -m prep.geometry` mengeluarkan `RuntimeWarning: '...' found in sys.modules...` sebelum mencetak `ok`. Itu **normal** (karena `prep/__init__.py` mengimpor submodulnya) dan bukan kegagalan.
- **Urutan tugas tidak boleh ditukar.** Task 2–5 memakai fungsi yang dibangun Task 1.

## Struktur Berkas

| Berkas | Tanggung jawab | Task |
|---|---|---|
| `prep/geometry.py` | Primitif geometri murni: `_bbox`, `fit_polylines`, `mirror_polylines`, pemusatan di `write_dxf`. Punya self-check `__main__` sendiri. | 1 |
| `prep/vector.py` | Re-fit setelah kontur bingkai dibuang; teruskan `target_height_mm` dan `mirror`. | 2, 3, 4 |
| `prep/raster.py` | `_trim_margin`; penskalaan fit-to-box; mirror. | 3, 4, 5 |
| `app.py` | Parameter Form baru: `height_mm`, `mirror`, `autotrim`. | 3, 4, 5 |
| `selfcheck.py` | Cek end-to-end; helper `_dxf_bbox`. | 2, 3, 4, 5 |
| `templates/index.html`, `README.md` | Kontrol UI dan dokumentasi. | 6 |

---

### Task 1: Primitif geometri + pemusatan DXF

Tiga hal di satu berkas, semuanya fungsi murni yang bisa diuji tanpa menyentuh HTTP: helper bbox bersama, `fit_polylines`, `mirror_polylines`, dan pemusatan di `write_dxf`.

**Files:**
- Modify: `prep/geometry.py` — sisipkan helper baru sebelum `write_dxf` (sekarang baris 115), ubah `write_dxf` (baris 115-122), tambah blok `__main__` di akhir berkas

**Interfaces:**
- Consumes: `Polyline = Tuple[List[Point], bool]` dan `Point = Tuple[float, float]`, keduanya sudah ada di `prep/geometry.py:15-16`.
- Produces (dipakai Task 2–4):
  - `_bbox(polylines: List[Polyline]) -> Tuple[float, float, float, float] | None` — `(xmin, ymin, xmax, ymax)`, `None` bila tak ada titik.
  - `fit_polylines(polylines: List[Polyline], target_width_mm: float, target_height_mm: float | None = None) -> Tuple[List[Polyline], Tuple[float, float]]`
  - `mirror_polylines(polylines: List[Polyline], width_mm: float) -> List[Polyline]`
  - `write_dxf(polylines: List[Polyline], out_path: str) -> None` — signature tidak berubah, tapi geometrinya kini berpusat di (0,0).

- [ ] **Step 1: Tulis self-check yang gagal**

Tambahkan di akhir `prep/geometry.py`:

```python
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

    print("ok")
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Expected: `NameError: name 'fit_polylines' is not defined`

- [ ] **Step 3: Tambahkan `_bbox` dan `fit_polylines`**

Sisipkan di `prep/geometry.py`, tepat sebelum `def write_dxf(`:

```python
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
        return polylines, (src_w, src_h)  # garis lurus sempurna: tak ada yang bisa diskalakan

    out = [
        ([((x - xmin) * scale, (y - ymin) * scale) for x, y in pts], closed)
        for pts, closed in polylines
    ]
    return out, (src_w * scale, src_h * scale)


def mirror_polylines(polylines: List[Polyline], width_mm: float) -> List[Polyline]:
    """Cermin horizontal: x -> width_mm - x. Urutan titik & status tertutup dipertahankan."""
    return [([(width_mm - x, y) for x, y in pts], closed) for pts, closed in polylines]
```

- [ ] **Step 4: Pusatkan geometri di `write_dxf`**

Ganti isi `write_dxf` (sekarang `prep/geometry.py:115-122`) menjadi:

```python
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
```

- [ ] **Step 5: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Expected: `ok` (didahului `RuntimeWarning` yang normal)

- [ ] **Step 6: Pastikan cek lain tidak rusak**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Expected: `ok`

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 7: Commit**

```bash
git add prep/geometry.py
git commit -m "feat: fit_polylines & mirror_polylines, pusatkan geometri DXF di (0,0)"
```

---

### Task 2: Perbaiki bug ukuran setelah kontur bingkai dibuang

Bug (a): `size_mm` dihitung sebelum `_drop_frame_and_speckle` membuang kontur, sehingga skala dipatok agar *bingkai* selebar target. Bingkai dibuang, subjeknya tinggal jauh lebih kecil, UI tetap melaporkan angka lama.

**Files:**
- Modify: `prep/vector.py:17` (import), `prep/vector.py:172-180`
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: `fit_polylines` dan `_bbox` dari Task 1.
- Produces (dipakai Task 3–5):
  - `selfcheck._dxf_bbox(path: str) -> Tuple[float, float, float, float]` — `(xmin, ymin, xmax, ymax)` dari semua LWPOLYLINE dalam sebuah DXF.
  - `selfcheck.check_frame_drop_size() -> None`, `selfcheck.check_dxf_centered() -> None`

- [ ] **Step 1: Tulis cek yang gagal**

Di `selfcheck.py`, tambahkan dua impor di blok impor atas (`cv2` dan `ezdxf`):

```python
import cv2
import ezdxf
```

Tambahkan helper tepat sesudah `_out_path`:

```python
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
```

Tambahkan dua cek tepat sebelum blok `if __name__ == "__main__":`:

```python
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
```

Tambahkan keduanya ke blok `__main__`, sehingga menjadi:

```python
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
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `AssertionError: lebar DXF nyata 16.xx mm, diminta 40` pada `check_frame_drop_size`.

`check_dxf_centered` seharusnya sudah LULUS — Task 1 sudah memusatkan DXF. Kalau justru cek itu yang gagal, hentikan dan laporkan: berarti Task 1 tidak berfungsi seperti yang diklaim.

- [ ] **Step 3: Hitung ulang ukuran dari kontur yang tersisa**

Di `prep/vector.py:17`, tambahkan `fit_polylines` ke impor:

```python
from .geometry import svg_to_polylines_mm, write_dxf, render_preview, Polyline, fit_polylines
```

Ganti blok di `process_raster_logo` (sekarang `prep/vector.py:172-177`) menjadi:

```python
    polylines, size_mm = svg_to_polylines_mm(
        svg_path, target_width_mm=target_width_mm, points_per_mm=points_per_mm
    )
    polylines = _drop_frame_and_speckle(polylines, size_mm)
    # Skala WAJIB dihitung ulang dari kontur yang tersisa. Kalau bingkai penuh-gambar
    # ikut terbuang, skala lama membuat BINGKAI selebar target — subjeknya jadi jauh
    # lebih kecil dari yang diminta, sementara size_mm lama tetap melaporkan target.
    polylines, size_mm = fit_polylines(polylines, target_width_mm)
    if not polylines:
        warnings.append("Tidak ada kontur terdeteksi. Coba matikan/hidupkan 'invert' atau ubah threshold.")
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 5: Commit**

```bash
git add prep/vector.py selfcheck.py
git commit -m "fix: hitung ulang ukuran dari kontur tersisa setelah bingkai dibuang"
```

---

### Task 3: Fit-to-box — batas tinggi maks

Fitur (e): kedua mode menerima batas tinggi opsional. Hasil dimuatkan ke dalam kotak lebar × tinggi tanpa mengubah rasio.

**Files:**
- Modify: `prep/vector.py` — signature `process_raster_logo` (sekarang baris 139-149) dan `process_svg_input` (baris 195-201), plus badan keduanya
- Modify: `prep/raster.py` — signature `process_photo` (sekarang baris 74-85), blok penskalaan (baris 130-135)
- Modify: `app.py` — parameter Form dan kedua pemanggilan
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: `fit_polylines(polylines, target_width_mm, target_height_mm=None)` dari Task 1; `_dxf_bbox` dari Task 2.
- Produces (dipakai Task 4–5):
  - `process_raster_logo(..., target_height_mm: float | None = None, ...)`
  - `process_svg_input(..., target_height_mm: float | None = None, ...)`
  - `process_photo(..., target_height_mm: float | None = None, ...)`
  - `app.process(..., height_mm: float = Form(0.0), ...)` — `0` berarti tak dipakai
  - `selfcheck._call` default bertambah `height_mm=0.0`

- [ ] **Step 1: Tulis cek yang gagal**

Di `selfcheck.py`, tambahkan `height_mm=0.0` ke dict `args` di dalam `_call`, sehingga menjadi:

```python
    args = dict(
        lp_sid=SID, job="grayscale", width_mm=20.0, height_mm=0.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
    )
```

Tambahkan cek tepat sebelum blok `if __name__ == "__main__":`:

```python
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
```

Tambahkan `check_fit_box()` ke blok `__main__`, sesudah `check_dxf_centered()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `TypeError: process() got an unexpected keyword argument 'height_mm'`

- [ ] **Step 3: Teruskan `target_height_mm` di cabang vektor**

Di `prep/vector.py`, tambahkan parameter pada `process_raster_logo` tepat sesudah `target_width_mm: float = 50.0,`:

```python
    target_height_mm: float | None = None,
```

Di badannya, ganti pemanggilan `fit_polylines` (dari Task 2) menjadi:

```python
    polylines, size_mm = fit_polylines(polylines, target_width_mm, target_height_mm)
```

Tambahkan parameter yang sama pada `process_svg_input`, dan ganti pemanggilan `svg_to_polylines_mm` di dalamnya menjadi:

```python
    polylines, size_mm = svg_to_polylines_mm(
        src_path,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
        points_per_mm=points_per_mm,
    )
```

Di **kedua** fungsi, tambahkan peringatan tepat sebelum `write_dxf(...)`:

```python
    if target_height_mm and size_mm[0] < target_width_mm - 0.05:
        warnings.append(
            f"Dibatasi tinggi maks — hasil {size_mm[0]:.1f} × {size_mm[1]:.1f} mm, "
            f"bukan {target_width_mm:.1f} mm lebar."
        )
```

- [ ] **Step 4: Teruskan `target_height_mm` di cabang grayscale**

Di `prep/raster.py`, tambahkan parameter pada `process_photo` tepat sesudah `target_width_mm: float = 50.0,`:

```python
    target_height_mm: float | None = None,
```

Ganti blok penskalaan fisik (sekarang `prep/raster.py:130-135`) menjadi:

```python
    # Penskalaan fisik: mm -> px pada DPI.
    h, w = gray.shape
    scale = (target_width_mm / 25.4 * dpi) / w
    if target_height_mm:
        # Muat DI DALAM kotak: sisi yang paling membatasi yang menentukan.
        scale = min(scale, (target_height_mm / 25.4 * dpi) / h)
    target_w_px = max(1, int(round(w * scale)))
    target_h_px = max(1, int(round(h * scale)))
    out_w_mm = target_w_px / dpi * 25.4
    target_h_mm = target_h_px / dpi * 25.4

    if target_height_mm and out_w_mm < target_width_mm - 0.05:
        warnings.append(
            f"Dibatasi tinggi maks — hasil {out_w_mm:.1f} × {target_h_mm:.1f} mm, "
            f"bukan {target_width_mm:.1f} mm lebar."
        )
```

Lalu di blok `return RasterResult(`, ganti baris `size_mm=(target_width_mm, target_h_mm),` menjadi:

```python
        size_mm=(out_w_mm, target_h_mm),
```

- [ ] **Step 5: Tambahkan parameter Form di `app.py`**

Tambahkan parameter tepat sesudah `width_mm: float = Form(50.0),`:

```python
    height_mm: float = Form(0.0),          # 0 = tanpa batas tinggi
```

Tepat sesudah blok validasi `width_mm` yang sudah ada, tambahkan:

```python
    try:
        height_mm = max(0.0, float(height_mm))
    except Exception:
        height_mm = 0.0
    target_h = height_mm if height_mm >= 1.0 else None
```

Teruskan `target_height_mm=target_h` pada ketiga pemanggilan: `process_svg_input`, `process_raster_logo`, dan `process_photo`.

- [ ] **Step 6: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 7: Commit**

```bash
git add prep/vector.py prep/raster.py app.py selfcheck.py
git commit -m "feat: fit-to-box — batas tinggi maks opsional di kedua mode"
```

---

### Task 4: Mirror horizontal

Fitur (d): satu opsi, kedua mode. Cabang vektor mencermin polyline (jalur yang sama untuk input raster maupun SVG); cabang grayscale membalik bitmap.

**Files:**
- Modify: `prep/vector.py` — impor, signature kedua fungsi, badan keduanya
- Modify: `prep/raster.py` — signature `process_photo`, sisipkan flip sebelum penskalaan
- Modify: `app.py` — parameter Form dan ketiga pemanggilan
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: `mirror_polylines(polylines, width_mm)` dari Task 1.
- Produces (dipakai Task 5): `mirror: bool = False` pada `process_raster_logo`, `process_svg_input`, `process_photo`; `app.process(..., mirror: bool = Form(False), ...)`; `selfcheck._call` default bertambah `mirror=False`.

- [ ] **Step 1: Tulis cek yang gagal**

Di `selfcheck.py`, tambahkan `mirror=False` ke dict `args` di dalam `_call`.

Tambahkan cek tepat sebelum blok `if __name__ == "__main__":`:

```python
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
            width_mm=76.2, dpi=100, mirror=m, autocontrast=False,
        )
        assert d["ok"], d
        outs[m] = np.asarray(Image.open(_out_path(d["downloads"][0]["url"])))
    assert outs[False].shape == (200, 300), outs[False].shape
    assert np.array_equal(outs[True], np.fliplr(outs[False])), "hasil mirror bukan cerminan"
```

Tambahkan `check_mirror()` ke blok `__main__`, sesudah `check_fit_box()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `TypeError: process() got an unexpected keyword argument 'mirror'`

- [ ] **Step 3: Cermin di cabang grayscale**

Di `prep/raster.py`, tambahkan parameter pada `process_photo` tepat sesudah `invert: bool = False,`:

```python
    mirror: bool = False,
```

Sisipkan tepat sesudah blok `if invert:` dan sebelum komentar `# Penskalaan fisik:`:

```python
    if mirror:
        # Kaca sering diukir dari sisi belakang; stempel & cetakan juga perlu tercermin.
        gray = cv2.flip(gray, 1)
```

- [ ] **Step 4: Cermin di cabang vektor**

Di `prep/vector.py:17`, tambahkan `mirror_polylines` ke impor:

```python
from .geometry import (
    svg_to_polylines_mm, write_dxf, render_preview, Polyline,
    fit_polylines, mirror_polylines,
)
```

Tambahkan parameter `mirror: bool = False,` pada `process_raster_logo` dan `process_svg_input`, tepat sesudah `target_height_mm`.

Di **kedua** fungsi, sisipkan **tepat sesudah blok peringatan tinggi dari Task 3** dan sebelum
`write_dxf(...)`. Urutannya wajib begitu: `mirror_polylines` memakai `size_mm[0]`, jadi ia harus
berjalan setelah `size_mm` final, dan sebelum `write_dxf` maupun `render_preview` supaya preview
menunjukkan apa yang benar-benar akan diukir.

```python
    if mirror:
        polylines = mirror_polylines(polylines, size_mm[0])
        warnings.append("Dicermin horizontal. Catatan: berkas SVG yang diunduh TIDAK ikut dicermin — pakai DXF.")
```

- [ ] **Step 5: Tambahkan parameter Form di `app.py`**

Tambahkan tepat sesudah `height_mm: float = Form(0.0),`:

```python
    mirror: bool = Form(False),
```

Teruskan `mirror=mirror` pada ketiga pemanggilan: `process_svg_input`, `process_raster_logo`, `process_photo`.

- [ ] **Step 6: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 7: Commit**

```bash
git add prep/vector.py prep/raster.py app.py selfcheck.py
git commit -m "feat: mirror horizontal di kedua mode"
```

---

### Task 5: Auto-trim margin polos (mode Grayscale)

Fitur (c): `process_photo` menskalakan seluruh kanvas termasuk margin kosong, sehingga "lebar 40 mm" bisa berarti 33 mm gambar + 7 mm udara. Trim dijalankan **sebelum** kontras, karena auto-kontras menghitung persentil atas seluruh gambar dan margin lebar menggeser hasilnya.

**Files:**
- Modify: `prep/raster.py` — helper baru, signature `process_photo`, sisipkan trim sesudah konversi grayscale (sekarang baris 104)
- Modify: `app.py` — parameter Form dan pemanggilan `process_photo`
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: tidak ada dari task sebelumnya.
- Produces: `prep.raster._trim_margin(gray: np.ndarray, tol: int = 12) -> Tuple[np.ndarray, bool]`; `process_photo(..., autotrim: bool = True)`; `app.process(..., autotrim: bool = Form(True))`; `selfcheck._call` default bertambah `autotrim=True`.

- [ ] **Step 1: Tulis cek yang gagal**

Di `selfcheck.py`, tambahkan `autotrim=True` ke dict `args` di dalam `_call` — nilai ini harus **sama dengan default di `app.py`** supaya cek menempuh jalur yang benar-benar dipakai operator.

Dua cek lama tidak membahas trim dan gambarnya kebetulan bermargin polos, jadi beri mereka `autotrim=False` secara eksplisit. Di `check_invert_grayscale`, ganti pemanggilannya menjadi:

```python
        d = _call(file=_upload("t.png", _png_bytes(arr)), invert=inv, autotrim=False)
```

Di `check_mirror`, ganti pemanggilannya menjadi:

```python
        d = _call(
            file=_upload("m.png", _png_bytes(arr)),
            width_mm=76.2, dpi=100, mirror=m, autocontrast=False, autotrim=False,
        )
```

Tambahkan cek baru tepat sebelum blok `if __name__ == "__main__":`:

```python
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
```

Tambahkan `check_autotrim()` ke blok `__main__`, sesudah `check_mirror()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `TypeError: process() got an unexpected keyword argument 'autotrim'`

- [ ] **Step 3: Tambahkan `_trim_margin`**

Di `prep/raster.py`, sisipkan tepat sesudah fungsi `_remove_bg_color` dan sebelum `def process_photo(`:

```python
def _trim_margin(gray: np.ndarray, tol: int = 12) -> Tuple[np.ndarray, bool]:
    """Buang margin polos di keempat sisi. Return (hasil, apakah_terpangkas).

    Latar diambil dari median piksel tepi — bukan diasumsikan putih — sehingga logo
    terang di latar gelap pun terpangkas benar. Bila seluruh gambar seragam (tak ada
    isi) atau isinya sudah menyentuh keempat tepi, gambar dikembalikan apa adanya.
    """
    h, w = gray.shape
    edge = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    bg = float(np.median(edge))
    mask = np.abs(gray.astype(np.int16) - bg) > tol
    if not mask.any():
        return gray, False
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    if (y0, x0) == (0, 0) and (y1, x1) == (h - 1, w - 1):
        return gray, False
    return gray[y0:y1 + 1, x0:x1 + 1], True
```

- [ ] **Step 4: Panggil trim sesudah konversi grayscale**

Di `prep/raster.py`, tambahkan parameter pada `process_photo` tepat sesudah `autocontrast: bool = True,`:

```python
    autotrim: bool = True,
```

Sisipkan tepat sesudah baris `gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)` dan sebelum `if clahe:`:

```python
    # Trim SEBELUM kontras: auto-kontras menghitung persentil atas seluruh gambar,
    # jadi margin kosong yang lebar akan menggeser hasilnya.
    if autotrim:
        gray, terpangkas = _trim_margin(gray)
        if terpangkas:
            warnings.append(
                "Margin polos dipangkas sebelum penskalaan — ukuran mm mengacu ke "
                "gambarnya, bukan kanvas."
            )
```

- [ ] **Step 5: Tambahkan parameter Form di `app.py`**

Tambahkan pada blok parameter raster, tepat sesudah `autocontrast: bool = Form(True),`:

```python
    autotrim: bool = Form(True),
```

Teruskan `autotrim=autotrim` pada pemanggilan `process_photo` (hanya cabang grayscale).

- [ ] **Step 6: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

```bash
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Expected: `ok`

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add prep/raster.py app.py selfcheck.py
git commit -m "feat: auto-trim margin polos sebelum penskalaan (mode Grayscale)"
```

---

### Task 6: Kontrol UI dan dokumentasi

Semua backend sudah selesai dan teruji. Task ini menyambungkannya ke layar operator dan memperbarui README.

**Files:**
- Modify: `templates/index.html` — kolom tinggi, dua checkbox mirror, satu checkbox auto-trim, pengiriman form
- Modify: `README.md` — daftar opsi pada langkah pemakaian, dan tips

**Interfaces:**
- Consumes: `app.process()` menerima `height_mm` (float, 0 = tanpa batas), `mirror` (bool), `autotrim` (bool, hanya grayscale).
- Produces: tidak ada antarmuka kode. Task terakhir.

- [ ] **Step 1: Tambahkan kolom Tinggi maks**

Di `templates/index.html`, ganti blok lebar target yang sekarang berbunyi:

```html
    <label>Lebar target (mm)</label>
    <input type="number" id="width_mm" value="40" min="1" step="1" />
    <div class="hint">Ukuran fisik hasil ukiran. Rasio tinggi dijaga otomatis.</div>
```

menjadi:

```html
    <div class="row">
      <div>
        <label>Lebar target (mm)</label>
        <input type="number" id="width_mm" value="40" min="1" step="1" />
      </div>
      <div>
        <label>Tinggi maks (mm)</label>
        <input type="number" id="height_mm" placeholder="opsional" min="1" step="1" />
      </div>
    </div>
    <div class="hint">Ukuran fisik hasil ukiran. <b>Tinggi maks kosong</b>: tinggi ikut rasio otomatis. <b>Diisi</b>: gambar dimuatkan ke dalam kotak lebar × tinggi, rasio tetap dijaga.</div>
```

- [ ] **Step 2: Tambahkan checkbox Mirror di kedua panel**

Di panel `#opts-vector`, tambahkan sesudah checkbox "Balik warna":

```html
      <label class="check"><input type="checkbox" id="mirror_vector" /> Cermin horizontal</label>
      <div class="hint">Membalik gambar kiri-kanan. Dipakai untuk stempel, cetakan, atau benda yang diukir dari sisi belakang. Berkas SVG yang diunduh tidak ikut dicermin — pakai DXF.</div>
```

Di panel `#opts-grayscale`, tambahkan sesudah checkbox "Balik (negatif)":

```html
      <label class="check"><input type="checkbox" id="mirror_gray" /> Cermin horizontal</label>
      <div class="hint">Membalik gambar kiri-kanan. Dipakai bila kaca diukir dari sisi belakang sehingga hasilnya terbaca benar dari depan.</div>
```

- [ ] **Step 3: Tambahkan checkbox Auto-trim**

Di panel `#opts-grayscale`, tambahkan sesudah checkbox "Auto-kontras":

```html
      <label class="check"><input type="checkbox" id="autotrim" checked /> Auto-trim margin polos</label>
      <div class="hint">Membuang tepi polos sebelum penskalaan, supaya "lebar 40 mm" berarti gambarnya 40 mm — bukan 33 mm gambar plus udara. Matikan bila kamu memang ingin bingkai kosongnya ikut terukir.</div>
```

- [ ] **Step 4: Kirim ketiga nilai baru dari form**

Di blok `$("#go").onclick`, tepat sesudah baris `fd.append("width_mm",$("#width_mm").value||"40");`, tambahkan:

```javascript
  fd.append("height_mm",$("#height_mm").value||"0");
```

Di dalam `if(job==="vector"){ ... }`, tambahkan:

```javascript
    fd.append("mirror",$("#mirror_vector").checked);
```

Di dalam blok `else { ... }` (grayscale), tambahkan:

```javascript
    fd.append("mirror",$("#mirror_gray").checked);
    fd.append("autotrim",$("#autotrim").checked);
```

- [ ] **Step 5: Verifikasi di browser**

```bash
docker compose up -d
```

Buka `http://127.0.0.1:8000` dan periksa satu per satu:

1. Kolom "Tinggi maks (mm)" tampil di sebelah "Lebar target (mm)", kosong secara default.
2. Checkbox "Cermin horizontal" muncul di **kedua** panel mode; "Auto-trim margin polos" muncul di panel Grayscale dan **sudah tercentang**.
3. Unggah `samples/logo.jpg` pada mode Vektor, lebar 40, tinggi maks kosong → chip "Ukuran" menunjukkan lebar ≈40 mm.
4. Ulangi dengan tinggi maks 20 → chip menunjukkan tinggi ≈20 mm dan muncul peringatan "Dibatasi tinggi maks".
5. Centang "Cermin horizontal", proses lagi → preview "sesudah" tercermin kiri-kanan, dan muncul catatan bahwa SVG tidak ikut dicermin.
6. Unggah `samples/photo.png` pada mode Grayscale, centang lalu hilangkan centang "Auto-trim" → keduanya diproses tanpa error.
7. Konsol browser bersih tanpa error di seluruh langkah di atas.

```bash
docker compose down
```

- [ ] **Step 6: Perbarui README**

Pada langkah pemakaian, ganti baris 3 dan 4 yang sekarang berbunyi:

```markdown
3. Isi **Lebar target (mm)** — ukuran fisik hasil ukiran (tinggi mengikuti rasio otomatis).
4. Atur opsi bila perlu (threshold, invert, speckle / DPI, kontras, gamma).
```

menjadi:

```markdown
3. Isi **Lebar target (mm)** — ukuran fisik hasil ukiran. Isi **Tinggi maks (mm)** bila
   hasilnya harus muat di area tertentu; kosongkan bila tinggi boleh ikut rasio.
4. Atur opsi bila perlu (threshold, invert, cermin, speckle / DPI, kontras, gamma,
   auto-trim).
```

Pada bagian **Tips kualitas**, tambahkan dua butir di akhir:

```markdown
- **Cermin horizontal**: untuk stempel, cetakan, dan kaca yang diukir dari sisi belakang
  supaya terbaca benar dari depan. Pada mode Vektor, berkas SVG yang diunduh tidak ikut
  dicermin — pakai DXF-nya.
- **Auto-trim** membuang tepi polos sebelum penskalaan, jadi ukuran mm mengacu ke gambarnya
  dan bukan ke kanvas. Matikan bila bingkai kosongnya memang ingin ikut terukir.
```

Pada tabel **Dua mode**, kolom "Yang dikerjakan Python", tambahkan `auto-trim` pada baris
Grayscale sehingga berbunyi:

```
Grayscale, auto-trim, auto-kontras/CLAHE, gamma, skala fisik mm @ DPI
```

- [ ] **Step 7: Jalankan seluruh cek terakhir kali**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

```bash
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Expected: `ok`

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add templates/index.html README.md
git commit -m "feat: kontrol tinggi maks, cermin, dan auto-trim di UI"
```

---

## Cakupan yang sengaja ditinggalkan

Menskalakan DXF/PLT passthrough — siklus sendiri: `.plt` adalah HPGL, bukan DXF, dan membaca DXF asing (ARC, CIRCLE, SPLINE, TEXT, INSERT) adalah subsistem tersendiri. Mirror vertikal — sama dengan putar 180° lalu cermin horizontal, tambahkan bila ternyata perlu. Pemrosesan banyak berkas sekaligus, rotate, dan preset tersimpan tetap di daftar fitur. Tetap di luar cakupan sesuai kesepakatan awal project: MarkEzd.dll (mark-ready level 2), input PDF/AI, teks hidup di SVG.
