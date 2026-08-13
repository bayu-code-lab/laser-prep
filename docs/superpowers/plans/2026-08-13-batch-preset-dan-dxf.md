# Batch, Preset, Area Kerja, Putar, dan DXF/PLT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Memproses banyak file sekaligus, menyimpan setelan yang dipakai berulang, melihat hasil terhadap area kerja lensa, memutar artwork, dan mengetahui ukuran berkas DXF/PLT pelanggan sebelum masuk EZCAD2.

**Architecture:** Batch dijalankan browser sebagai permintaan `/process` berurutan dengan penanda `reset` untuk file pertama; endpoint baru `POST /zip` mengemas hasil pilihan. Putar jadi transformasi bersama di kedua mode dengan urutan yang dipatok (putar dulu, baru cermin). Modul baru `prep/passthrough.py` membaca ukuran DXF (lewat `ezdxf.bbox`) dan PLT (pengurai HPGL sendiri), dan hanya menskalakan bila operator memintanya. Preset dan daftar lensa hidup di `localStorage`, tanpa keadaan di server.

**Tech Stack:** Python 3 + FastAPI, OpenCV (`opencv-python-headless`), Pillow, NumPy, `ezdxf` 1.4.4, `vtracer`, `svgpathtools`. Frontend: HTML + JS polos tanpa framework. Semua dijalankan lewat Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-13-batch-preset-dan-dxf-design.md`

## Global Constraints

- **Tanpa dependensi baru.** Tidak ada pytest, tidak ada httpx, tidak ada paket baru di `requirements.txt`. Pengujian memakai `assert` polos di blok `__main__` dan `selfcheck.py`.
- **`cv2` tidak terpasang di host.** SETIAP perintah Python wajib lewat
  `docker compose run --rm --no-deps laser-prep python <...>` — dijalankan dari akar repo.
- **`selfcheck.py` memanggil `app.process()` langsung**, bukan lewat HTTP, supaya bug penyambungan parameter di `app.py` ikut tertangkap. Jangan mengubah pola ini.
- **Bahasa Indonesia** untuk seluruh komentar, docstring, pesan peringatan/galat, dan teks UI. Istilah teknis yang sudah baku (`threshold`, `speckle`, `passthrough`, `commit`) boleh tetap bahasa Inggris.
- **Setiap cek baru wajib DILIHAT GAGAL lebih dulu** terhadap kode sebelum perbaikan, lalu dilihat lulus sesudahnya. Cek yang tidak pernah terlihat merah tidak membuktikan apa pun.
- **Urutan transformasi dipatok: putar dulu, baru cermin**, sama di kedua mode.
- **Arah putar: searah jarum jam sebagaimana terlihat di layar**, sama di kedua mode.
- **`_out` adalah tmpfs 256 MB.** Jangan menulis berkas sementara berukuran besar ke dalamnya.
- **Nama fitur mengikuti format keluaran**, bukan nama mesin: "Ke Vektor (DXF)" dan "Ke Grayscale (PNG)". Jangan memperkenalkan kembali "MOPA"/"UV" di UI.
- **Komentar `ponytail:`** dipakai untuk menandai penyederhanaan yang disengaja, disertai jalan naiknya.

---

### Task 1: `rotate_polylines` di geometry.py

Fungsi murni yang memutar polyline. Ini mematok **arah** putaran untuk seluruh jalur vektor, jadi ceknya harus menyebut koordinat yang tepat, bukan sekadar "lebar dan tinggi tertukar".

**Files:**
- Modify: `prep/geometry.py` (tambah fungsi setelah `mirror_polylines`, baris ~161; tambah cek di blok `__main__`)

**Interfaces:**
- Consumes: `Polyline = Tuple[List[Point], bool]` yang sudah ada di `prep/geometry.py`.
- Produces: `rotate_polylines(polylines: List[Polyline], deg: int) -> List[Polyline]` — dipakai Task 3 dan Task 7.

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan tepat sebelum `print("ok")` di blok `__main__` `prep/geometry.py`:

```python
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
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Diharapkan: `NameError: name 'rotate_polylines' is not defined`.

- [ ] **Step 3: Implementasi**

Tambahkan di `prep/geometry.py` setelah `mirror_polylines`:

```python
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
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.geometry
```

Diharapkan: `ok`.

- [ ] **Step 5: Commit**

```bash
git add prep/geometry.py
git commit -m "feat(geometry): rotate_polylines 0/90/180/270 searah jarum jam"
```

---

### Task 2: Putar di mode Grayscale

Menerapkan putar di `prep/raster.py` dan menyambungkan parameter `rotate` di `app.py` **hanya untuk cabang grayscale**. Cabang vektor menyusul di Task 3.

Tiga cek sekaligus di sini karena ketiganya menguji satu perilaku yang sama dari sisi berbeda, dan ketiganya butuh jalur yang sama sudah hidup.

**Files:**
- Modify: `prep/raster.py` (tambah parameter `rotate`, sisipkan rotasi sebelum cermin, baris ~163)
- Modify: `app.py` (tambah `rotate: int = Form(0)` ke tanda tangan `process()`, teruskan ke `process_photo`)
- Modify: `selfcheck.py` (tambah `rotate=0` ke default `_call`, tambah tiga fungsi cek, daftarkan di `__main__`)

**Interfaces:**
- Consumes: `process_photo(...)` yang ada di `prep/raster.py`.
- Produces: parameter form `rotate: int` pada `POST /process` (dipakai Task 3 dan Task 7); `process_photo(..., rotate: int = 0)`.

- [ ] **Step 1: Tulis cek yang gagal**

Di `selfcheck.py`, tambahkan `rotate=0` ke dict default di `_call`:

```python
    args = dict(
        lp_sid=SID, job="grayscale", width_mm=20.0, height_mm=0.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
        mirror=False, autotrim=True, rotate=0,
    )
```

Lalu tambahkan tiga fungsi:

```python
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
```

Daftarkan ketiganya di blok `__main__` setelah `check_autotrim()`:

```python
        check_rotate_grayscale()
        check_rotate_size_swap()
        check_rotate_mirror_order()
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `TypeError: process() got an unexpected keyword argument 'rotate'`.

- [ ] **Step 3: Implementasi di `prep/raster.py`**

Tambahkan tabel konstanta setelah blok `import` (di bawah `from PIL import Image`):

```python
# Putar searah jarum jam sebagaimana terlihat di layar — arah yang sama dipakai
# rotate_polylines() di prep/geometry.py untuk mode Vektor.
_CV_ROT = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}
```

Tambahkan parameter pada `process_photo` (setelah `mirror: bool = False,`):

```python
    rotate: int = 0,
```

Ganti blok `if mirror:` yang ada (baris ~163-165) dengan:

```python
    # Putar SEBELUM cermin. Untuk 90°/270° kedua operasi ini tidak komutatif, dan
    # mode Vektor memakai urutan yang sama (putar -> fit -> cermin). Urutan yang
    # berbeda antar mode akan memberi dua jawaban untuk setelan yang sama.
    if int(rotate) in _CV_ROT:
        gray = cv2.rotate(gray, _CV_ROT[int(rotate)])

    if mirror:
        # Kaca sering diukir dari sisi belakang; stempel & cetakan juga perlu tercermin.
        gray = cv2.flip(gray, 1)
```

Penskalaan di bawahnya membaca `h, w = gray.shape`, jadi otomatis memakai dimensi hasil putaran — tidak ada perubahan lain yang diperlukan.

- [ ] **Step 4: Implementasi di `app.py`**

Tambahkan ke tanda tangan `process()` tepat setelah `mirror: bool = Form(False),`:

```python
    rotate: int = Form(0),                # 0 | 90 | 180 | 270
```

Tambahkan normalisasi tepat setelah blok validasi `height_mm` yang ada:

```python
    try:
        rotate = int(rotate) % 360
    except Exception:
        rotate = 0
    if rotate not in (90, 180, 270):
        rotate = 0
```

Teruskan ke `process_photo` (tambahkan argumen setelah `mirror=mirror,`):

```python
                rotate=rotate,
```

- [ ] **Step 5: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `selfcheck ok`.

- [ ] **Step 6: Commit**

```bash
git add prep/raster.py app.py selfcheck.py
git commit -m "feat(grayscale): putar 0/90/180/270 sebelum cermin"
```

---

### Task 3: Putar di mode Vektor

Menyambungkan `rotate` ke kedua fungsi vektor. Ada satu perubahan yang lebih dari sekadar menyisipkan: `process_svg_input` sekarang menyerahkan penskalaan ke `svg_to_polylines_mm`, yang berarti target ukuran ditafsirkan **sebelum** putaran. Itu harus dipindah ke `fit_polylines` supaya "lebar 40 mm" merujuk hasil akhir — persis seperti yang sudah dilakukan `process_raster_logo`.

**Files:**
- Modify: `prep/vector.py` (import, dua tanda tangan fungsi, dua tempat penyisipan)
- Modify: `app.py` (teruskan `rotate` ke kedua fungsi vektor)
- Modify: `selfcheck.py` (helper `_dxf_centroid`, cek `check_rotate_vector`)

**Interfaces:**
- Consumes: `rotate_polylines(polylines, deg)` dari Task 1; parameter form `rotate` dari Task 2.
- Produces: `process_raster_logo(..., rotate: int = 0)` dan `process_svg_input(..., rotate: int = 0)`.

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan helper di `selfcheck.py` tepat setelah `_dxf_bbox`:

```python
def _dxf_centroid(path: str) -> tuple:
    """Rata-rata posisi semua verteks LWPOLYLINE. Cukup untuk menjawab
    'ke arah mana bentuknya berputar' — bbox tidak bisa, karena bbox bentuk L
    tetap persegi ke arah mana pun ia diputar."""
    doc = ezdxf.readfile(path)
    pts = [p for e in doc.modelspace().query("LWPOLYLINE") for p in e.get_points("xy")]
    assert pts, f"DXF tidak memuat polyline: {path}"
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
```

Tambahkan cek:

```python
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
```

Daftarkan di `__main__` setelah `check_rotate_mirror_order()`:

```python
        check_rotate_vector()
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `AssertionError: arah putaran vektor salah: ...` (parameter `rotate` diterima `app.py` tapi belum diteruskan ke jalur vektor, jadi 0° dan 90° menghasilkan titik berat identik).

- [ ] **Step 3: Implementasi di `prep/vector.py`**

Tambahkan `rotate_polylines` ke daftar import dari `.geometry`:

```python
from .geometry import (
    svg_to_polylines_mm, write_dxf, render_preview, Polyline,
    fit_polylines, mirror_polylines, rotate_polylines, _bbox,
)
```

Pada `process_raster_logo`, tambahkan parameter setelah `mirror: bool = False,`:

```python
    rotate: int = 0,
```

Lalu sisipkan tepat sebelum baris `polylines, size_mm = fit_polylines(...)` (baris ~203, sesudah blok resampling kepadatan):

```python
    # Putar SEBELUM fit: dengan begitu "lebar target" merujuk lebar hasil AKHIR,
    # bukan lebar sebelum diputar. Cermin tetap sesudah fit karena
    # mirror_polylines butuh lebar akhir — urutan efektifnya jadi putar -> cermin,
    # sama dengan mode Grayscale.
    polylines = rotate_polylines(polylines, rotate)
```

Pada `process_svg_input`, tambahkan parameter yang sama setelah `mirror: bool = False,`:

```python
    rotate: int = 0,
```

Lalu **ganti** blok pemanggilan `svg_to_polylines_mm` yang ada (baris ~245-250) dengan:

```python
    # Sampling memakai target_width_mm supaya kepadatan titiknya kira-kira benar,
    # tapi ukuran AKHIR ditentukan fit_polylines SESUDAH putaran — kalau target
    # tinggi diterapkan di sini, ia akan menafsirkan kotak dalam orientasi sebelum
    # diputar. Alur ini kini sama persis dengan process_raster_logo.
    polylines, size_mm = svg_to_polylines_mm(
        src_path,
        target_width_mm=target_width_mm,
        points_per_mm=points_per_mm,
    )
    polylines = rotate_polylines(polylines, rotate)
    polylines, size_mm = fit_polylines(polylines, target_width_mm, target_height_mm)
```

- [ ] **Step 4: Implementasi di `app.py`**

Tambahkan `rotate=rotate,` ke pemanggilan `process_svg_input(...)` dan `process_raster_logo(...)` di cabang `job == "vector"`.

- [ ] **Step 5: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Diharapkan: `selfcheck ok` dan `ok`. `check_fit_box` dan `check_frame_drop_size` yang sudah ada wajib tetap hijau — keduanya melewati jalur yang baru diubah.

- [ ] **Step 6: Commit**

```bash
git add prep/vector.py app.py selfcheck.py
git commit -m "feat(vektor): putar sebelum fit, arah sama dengan grayscale"
```

---

### Task 4: Batch — parameter `reset` dan anggaran ruang

**Files:**
- Modify: `app.py` (konstanta `BATCH_BUDGET`, helper `_dir_size`, parameter `reset`, cabang pembuatan folder sesi, penolakan saat ruang habis)
- Modify: `selfcheck.py` (tambah `reset=True` ke default `_call`, dua cek baru)

**Interfaces:**
- Consumes: `_fresh_session_dir(sid)` dan `OUT_DIR` yang sudah ada di `app.py`.
- Produces: parameter form `reset: bool` pada `POST /process`; konstanta modul `appmod.BATCH_BUDGET` (dipakai cek untuk menurunkan ambang sementara).

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan `reset=True` ke dict default `_call` di `selfcheck.py`:

```python
        mirror=False, autotrim=True, rotate=0, reset=True,
```

Tambahkan dua cek:

```python
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
        d2 = _call(file=_upload("b.png", _png_bytes(arr)), reset=False, autotrim=False)
    finally:
        appmod.BATCH_BUDGET = asli
    assert not d2["ok"], "file kedua seharusnya ditolak saat ruang habis"
    assert "penuh" in d2["error"].lower(), d2["error"]
    assert os.path.exists(p1), "hasil yang sudah ada tidak boleh ikut hilang"
```

Daftarkan keduanya di `__main__` setelah `check_rotate_vector()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `TypeError: process() got an unexpected keyword argument 'reset'`.

- [ ] **Step 3: Implementasi**

Di `app.py`, tambahkan setelah konstanta `SESSION_TTL`:

```python
# Batas total hasil dalam satu folder sesi. _out adalah tmpfs 256 MB; sisanya
# headroom supaya batch berhenti dengan pesan yang jelas, bukan dengan
# "No space left on device" di tengah penulisan berkas.
BATCH_BUDGET = 200 * 1024 * 1024
```

Tambahkan helper setelah `_fresh_session_dir`:

```python
def _dir_size(d: str) -> int:
    """Total byte berkas biasa langsung di dalam d (folder sesi tidak bersarang)."""
    total = 0
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            total += os.path.getsize(p)
    return total
```

Tambahkan parameter ke `process()` tepat setelah `job: str = Form(...),`:

```python
    reset: bool = Form(True),             # True = kosongkan folder sesi (file pertama batch)
```

**Ganti** dua baris pembuka badan fungsi:

```python
    sid = re.sub(r"[^a-f0-9]", "", lp_sid)[:32] or uuid.uuid4().hex
    sess_dir = _fresh_session_dir(sid)
    _gc_sessions()
```

dengan:

```python
    sid = re.sub(r"[^a-f0-9]", "", lp_sid)[:32] or uuid.uuid4().hex
    if reset:
        sess_dir = _fresh_session_dir(sid)
    else:
        # File ke-2 dan seterusnya dalam satu batch menumpang folder yang sama —
        # mengosongkannya di sini akan memakan hasil file-file sebelumnya.
        sess_dir = os.path.join(OUT_DIR, sid)
        os.makedirs(sess_dir, exist_ok=True)
    _gc_sessions()

    if _dir_size(sess_dir) >= BATCH_BUDGET:
        # Status 200, bukan 500: ini kondisi yang diharapkan, bukan kesalahan
        # server, dan gelung batch di browser merendernya lewat jalur galat
        # yang sama dengan galat lain.
        return JSONResponse({
            "ok": False,
            "error": f"Ruang hasil penuh ({BATCH_BUDGET // (1024 * 1024)} MB). "
                     f"File ini tidak diproses — unduh hasil yang sudah ada, "
                     f"lalu proses sisanya sebagai batch baru.",
        })
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `selfcheck ok`.

- [ ] **Step 5: Commit**

```bash
git add app.py selfcheck.py
git commit -m "feat(batch): parameter reset dan anggaran ruang folder sesi"
```

---

### Task 5: Endpoint `POST /zip`

**Files:**
- Modify: `app.py` (import, regex nama aman, endpoint `zip_outputs`)
- Modify: `selfcheck.py` (import `zipfile` dan `HTTPException`, cek `check_zip`)

**Interfaces:**
- Consumes: `OUT_DIR` dari `app.py`.
- Produces: `zip_outputs(lp_sid: str, names: list[str]) -> FileResponse` — dipanggil langsung oleh `selfcheck.py`, dan lewat HTTP oleh UI di Task 8.

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan import di `selfcheck.py`:

```python
import zipfile
```

dan pada baris import fastapi:

```python
from fastapi import UploadFile, HTTPException
```

Tambahkan cek:

```python
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
    for jahat in ["../app.py", "a/b.png", "..", ""]:
        try:
            appmod.zip_outputs(lp_sid=SID, names=[jahat])
        except HTTPException:
            pass
        else:
            raise AssertionError(f"nama berbahaya lolos: {jahat!r}")
```

Daftarkan di `__main__` setelah `check_batch_budget()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `AttributeError: module 'app' has no attribute 'zip_outputs'`.

- [ ] **Step 3: Implementasi**

Di `app.py`, tambahkan ke blok import:

```python
import tempfile
import zipfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Cookie, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from starlette.background import BackgroundTask
```

Tambahkan konstanta di dekat `BATCH_BUDGET`:

```python
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
```

Tambahkan endpoint setelah `process()`:

```python
@app.post("/zip")
def zip_outputs(lp_sid: str = Cookie(default=""), names: list[str] = Body(..., embed=True)):
    """Kemas berkas hasil pilihan dari folder sesi ini jadi satu ZIP.

    Daftar nama datang dari browser, bukan hasil tebakan atas isi folder:
    menebak berarti menyaring dengan pola nama (_before.jpg, _after.png), dan
    pola itu rusak diam-diam begitu ada berkas baru bernama mirip.
    """
    sid = re.sub(r"[^a-f0-9]", "", lp_sid)[:32]
    sess_dir = os.path.join(OUT_DIR, sid)
    if not sid or not os.path.isdir(sess_dir):
        raise HTTPException(400, "Sesi tidak ditemukan.")

    paths = []
    for n in names:
        # Wajib basename polos DAN benar-benar ada di folder sesi ini. Tanpa ini,
        # "../app.py" akan mengemas berkas di luar folder sesi.
        if not n or n in (".", "..") or not _SAFE_NAME.match(n):
            raise HTTPException(400, f"Nama berkas tidak sah: {n!r}")
        p = os.path.join(sess_dir, n)
        if not os.path.isfile(p):
            raise HTTPException(400, f"Berkas tidak ada di sesi ini: {n}")
        paths.append(p)
    if not paths:
        raise HTTPException(400, "Tidak ada berkas untuk dikemas.")

    # Temp file DI LUAR _out: _out adalah tmpfs 256 MB, dan mengemas hasil di
    # dalamnya berarti memakai ruang dua kali lipat lalu menjebolnya.
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, arcname=os.path.basename(p))
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"laser-prep-{sid[:6]}.zip",
        background=BackgroundTask(os.remove, tmp.name),
    )
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `selfcheck ok`.

- [ ] **Step 5: Commit**

```bash
git add app.py selfcheck.py
git commit -m "feat: endpoint POST /zip untuk mengunduh hasil batch sekaligus"
```

---

### Task 6: `prep/passthrough.py` — baca ukuran DXF & PLT

Modul baru. Belum disambungkan ke `app.py` — itu Task 7. Diuji lewat blok `__main__`-nya sendiri.

**Files:**
- Create: `prep/passthrough.py`
- Modify: `prep/__init__.py` (ekspor `read_size`, `plt_to_polylines`, `scale_to_dxf`)

**Interfaces:**
- Consumes: `_bbox`, `Polyline`, `fit_polylines`, `rotate_polylines`, `write_dxf` dari `prep/geometry.py`.
- Produces:
  - `read_size(path: str) -> Tuple[float, float, List[str]]` — (lebar_mm, tinggi_mm, warnings)
  - `plt_to_polylines(path: str) -> List[Polyline]` — polyline dalam mm
  - `scale_to_dxf(src_path: str, out_path: str, target_width_mm: float, target_height_mm: float | None = None, rotate: int = 0) -> Tuple[float, float]` — menulis DXF dan mengembalikan ukuran akhir (lebar_mm, tinggi_mm)

- [ ] **Step 1: Tulis modul beserta cek yang gagal**

Buat `prep/passthrough.py` **hanya dengan blok `__main__` dan docstring modul** dulu, supaya ceknya benar-benar terlihat merah:

```python
"""
Berkas vektor kiriman pelanggan: .dxf dan .plt.

Beda dari mode Vektor — di sini tidak ada penelusuran raster. Tugas modul ini
menjawab "ukurannya berapa, muat tidak" tanpa merusak berkas yang sudah benar,
dan hanya menskalakan bila operator memintanya secara eksplisit.
"""
from __future__ import annotations
import math
import os
import re
from typing import List, Tuple

import ezdxf
import ezdxf.bbox
import ezdxf.transform
from ezdxf import units as ezunits

from .geometry import Polyline, _bbox, fit_polylines, rotate_polylines, write_dxf


if __name__ == "__main__":
    import tempfile

    # --- PLT: 4000 satuan plotter = 100 mm, 2000 = 50 mm (40 satuan/mm) ---
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.plt")
        with open(p, "w") as f:
            f.write("IN;SP1;PU0,0;PD4000,0;PD4000,2000;PU;")
        w, h, warn = read_size(p)
        assert abs(w - 100.0) < 1e-6 and abs(h - 50.0) < 1e-6, (w, h)
        assert warn == [], warn
        polys = plt_to_polylines(p)
        assert len(polys) == 1 and len(polys[0][0]) == 3, polys

        # PR (koordinat relatif) harus BERHENTI, bukan melaporkan angka yang salah
        pr = os.path.join(d, "r.plt")
        with open(pr, "w") as f:
            f.write("IN;PU0,0;PR;PD100,100;")
        try:
            read_size(pr)
        except ValueError as e:
            assert "relatif" in str(e).lower(), str(e)
        else:
            raise AssertionError("PLT dengan PR seharusnya menaikkan galat")

        # PLT tanpa garis sama sekali = galat, bukan 0 x 0
        kosong = os.path.join(d, "k.plt")
        with open(kosong, "w") as f:
            f.write("IN;SP1;PU;")
        try:
            read_size(kosong)
        except ValueError:
            pass
        else:
            raise AssertionError("PLT kosong seharusnya menaikkan galat")

        # --- DXF dalam mm: 30 x 12 ---
        doc = ezdxf.new("R2010")
        doc.units = ezunits.MM
        doc.modelspace().add_lwpolyline(
            [(5, 5), (35, 5), (35, 17), (5, 17)], close=True)
        dxf_mm = os.path.join(d, "mm.dxf")
        doc.saveas(dxf_mm)
        w, h, warn = read_size(dxf_mm)
        assert abs(w - 30.0) < 1e-6 and abs(h - 12.0) < 1e-6, (w, h)
        assert warn == [], warn

        # --- DXF inci: koordinat sama, tapi $INSUNITS=1 -> 25.4x lebih besar ---
        # $INSUNITS diset lewat header, bukan lewat konstanta ezdxf.units, supaya
        # cek ini tidak bergantung pada nama konstanta versi ezdxf tertentu.
        doc_in = ezdxf.new("R2010")
        doc_in.header["$INSUNITS"] = 1
        doc_in.modelspace().add_lwpolyline([(0, 0), (2, 0), (2, 1), (0, 1)], close=True)
        dxf_in = os.path.join(d, "in.dxf")
        doc_in.saveas(dxf_in)
        w, h, warn = read_size(dxf_in)
        assert abs(w - 50.8) < 1e-6 and abs(h - 25.4) < 1e-6, (w, h)

        # --- DXF tanpa satuan: angka dilaporkan apa adanya + PERINGATAN ---
        doc_u = ezdxf.new("R2010")
        doc_u.header["$INSUNITS"] = 0
        doc_u.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 4), (0, 4)], close=True)
        dxf_u = os.path.join(d, "u.dxf")
        doc_u.saveas(dxf_u)
        w, h, warn = read_size(dxf_u)
        assert abs(w - 10.0) < 1e-6 and abs(h - 4.0) < 1e-6, (w, h)
        assert warn and "satuan" in warn[0].lower(), warn

        # --- Penskalaan: lebar jadi 60 mm, dan hasilnya terpusat di (0,0) ---
        out = os.path.join(d, "out.dxf")
        size = scale_to_dxf(dxf_mm, out, target_width_mm=60.0)
        assert abs(size[0] - 60.0) < 1e-3 and abs(size[1] - 24.0) < 1e-3, size
        pts = [p for e in ezdxf.readfile(out).modelspace().query("LWPOLYLINE")
               for p in e.get_points("xy")]
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        assert abs(cx) < 1e-3 and abs(cy) < 1e-3, f"DXF hasil harus terpusat di (0,0): ({cx}, {cy})"
        lebar = max(p[0] for p in pts) - min(p[0] for p in pts)
        assert abs(lebar - 60.0) < 1e-3, lebar

        # --- Penskalaan + putar 90°: lebar dan tinggi tertukar ---
        out90 = os.path.join(d, "out90.dxf")
        size90 = scale_to_dxf(dxf_mm, out90, target_width_mm=60.0, rotate=90)
        # sumber 30x12 diputar jadi 12x30, lalu dilebarkan ke 60 -> tinggi 150
        assert abs(size90[0] - 60.0) < 1e-3 and abs(size90[1] - 150.0) < 1e-2, size90

        # --- PLT yang diskalakan keluar sebagai DXF ---
        outp = os.path.join(d, "p.dxf")
        sizep = scale_to_dxf(p, outp, target_width_mm=200.0)
        assert abs(sizep[0] - 200.0) < 1e-3 and abs(sizep[1] - 100.0) < 1e-2, sizep

    print("ok")
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.passthrough
```

Diharapkan: `NameError: name 'read_size' is not defined`.

- [ ] **Step 3: Implementasi**

Sisipkan di `prep/passthrough.py` di antara blok import dan blok `__main__`:

```python
PLT_UNIT_MM = 0.025          # 1 satuan plotter HPGL = 0.025 mm (40 satuan/mm)

# $INSUNITS DXF -> faktor ke mm. Kunci yang tidak ada di sini diperlakukan
# seperti 0 (tanpa satuan): angkanya dipakai apa adanya, disertai peringatan.
_INSUNITS_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 13: 0.001, 14: 100.0}

# HPGL: dua huruf perintah lalu parameternya sampai huruf berikutnya atau ';'.
_HPGL_CMD = re.compile(r"([A-Za-z]{2})([^A-Za-z;]*)")


def plt_to_polylines(path: str) -> List[Polyline]:
    """Urai HPGL (.plt) jadi polyline dalam mm.

    Hanya gerak ABSOLUT (PU/PD/PA) yang didukung. Bila file memakai koordinat
    relatif (PR), fungsi ini berhenti dengan galat alih-alih melaporkan ukuran
    yang salah — diam-diam salah jauh lebih mahal daripada berhenti.
    """
    with open(path, "r", errors="ignore") as f:
        teks = f.read()

    polylines: List[Polyline] = []
    berjalan: List[Tuple[float, float]] = []
    pena_turun = False
    posisi: Tuple[float, float] | None = None

    def tutup() -> None:
        nonlocal berjalan
        if len(berjalan) >= 2:
            polylines.append((berjalan, False))
        berjalan = []

    for cmd, args in _HPGL_CMD.findall(teks):
        c = cmd.upper()
        if c == "PR":
            raise ValueError(
                "File PLT memakai koordinat relatif (PR) — belum didukung. "
                "Ekspor ulang dari sumbernya dengan koordinat absolut, atau kirim DXF."
            )
        if c not in ("PU", "PD", "PA"):
            continue
        angka = [a for a in re.split(r"[,\s]+", args.strip()) if a]
        titik: List[Tuple[float, float]] = []
        for i in range(0, len(angka) - 1, 2):
            try:
                titik.append(
                    (float(angka[i]) * PLT_UNIT_MM, float(angka[i + 1]) * PLT_UNIT_MM)
                )
            except ValueError:
                pass                      # parameter non-koordinat, abaikan
        if c == "PU":
            tutup()
            pena_turun = False
            if titik:
                posisi = titik[-1]
        elif c == "PD":
            pena_turun = True
            if posisi is not None and not berjalan:
                berjalan = [posisi]
            for t in titik:
                berjalan.append(t)
                posisi = t
        else:                             # PA: gerak absolut, mengikuti keadaan pena
            for t in titik:
                if pena_turun:
                    if not berjalan and posisi is not None:
                        berjalan = [posisi]
                    berjalan.append(t)
                posisi = t
    tutup()
    return polylines


def _dxf_extents(doc) -> Tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) modelspace dalam satuan asli file."""
    kotak = ezdxf.bbox.extents(doc.modelspace())
    if not kotak.has_data:
        raise ValueError("File DXF tidak memuat geometri yang bisa dibaca.")
    return kotak.extmin.x, kotak.extmin.y, kotak.extmax.x, kotak.extmax.y


def read_size(path: str) -> Tuple[float, float, List[str]]:
    """(lebar_mm, tinggi_mm, warnings) untuk berkas .dxf atau .plt."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".plt":
        box = _bbox(plt_to_polylines(path))
        if box is None:
            raise ValueError("File PLT tidak memuat garis yang bisa dibaca.")
        return box[2] - box[0], box[3] - box[1], []

    if ext == ".dxf":
        doc = ezdxf.readfile(path)
        x0, y0, x1, y1 = _dxf_extents(doc)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
        faktor = _INSUNITS_MM.get(insunits)
        warnings: List[str] = []
        if faktor is None:
            faktor = 1.0
            warnings.append(
                "File DXF tidak menyatakan satuannya ($INSUNITS=0) — ukuran di atas "
                "dianggap milimeter. Periksa di EZCAD2 bila terasa janggal."
            )
        return (x1 - x0) * faktor, (y1 - y0) * faktor, warnings

    raise ValueError(f"Format {ext} bukan DXF/PLT.")


def scale_to_dxf(
    src_path: str,
    out_path: str,
    target_width_mm: float,
    target_height_mm: float | None = None,
    rotate: int = 0,
) -> Tuple[float, float]:
    """Skalakan (dan putar) berkas vektor pelanggan, tulis sebagai DXF mm terpusat di (0,0).

    .plt keluar sebagai DXF juga, bukan PLT: setelah terurai jadi polyline,
    fit_polylines + write_dxf yang sudah teruji langsung terpakai — termasuk
    pemusatan di (0,0). Menulis HPGL kembali berarti kode baru tanpa penguji
    untuk hasil yang lebih jelek; EZCAD2 membaca DXF sama baiknya.

    Return (lebar_mm, tinggi_mm) hasil akhir.
    """
    ext = os.path.splitext(src_path)[1].lower()

    if ext == ".plt":
        polys = rotate_polylines(plt_to_polylines(src_path), rotate)
        polys, size = fit_polylines(polys, target_width_mm, target_height_mm)
        write_dxf(polys, out_path)
        return size

    if ext != ".dxf":
        raise ValueError(f"Format {ext} bukan DXF/PLT.")

    # DXF SENGAJA tidak diratakan jadi polyline: transform ezdxf mempertahankan
    # busur, spline, dan blok apa adanya. Harganya, tidak ada pratinjau gambar
    # untuk DXF.
    # ponytail: kalau pratinjau DXF nanti diperlukan, ratakan dengan ezdxf.path
    # KHUSUS untuk pratinjau, jangan untuk berkas keluarannya.
    doc = ezdxf.readfile(src_path)
    # list(...) bukan modelspace-nya langsung: helper ezdxf.transform menerima
    # Iterable[DXFEntity], dan daftar konkret menghilangkan pertanyaan apakah
    # iterasi tetap sah sementara entitasnya sedang diubah.
    msp = list(doc.modelspace())

    if rotate in (90, 180, 270):
        # ezdxf memutar berlawanan jarum jam untuk sudut positif; kita ingin
        # searah jarum jam, arah yang sama dengan rotate_polylines dan cv2.rotate.
        ezdxf.transform.z_rotate(msp, -math.radians(rotate))

    x0, y0, x1, y1 = _dxf_extents(doc)
    src_w, src_h = x1 - x0, y1 - y0
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Geometri DXF merosot (lebar atau tinggi nol).")

    # Faktor dihitung dari koordinat MENTAH, dan doc.units dipaksa MM di bawah:
    # dengan begitu satuan asal file tidak ikut masuk hitungan dua kali.
    faktor = target_width_mm / src_w
    if target_height_mm:
        faktor = min(faktor, target_height_mm / src_h)
    ezdxf.transform.scale_uniform(msp, faktor)

    x0, y0, x1, y1 = _dxf_extents(doc)
    ezdxf.transform.translate(msp, (-(x0 + x1) / 2, -(y0 + y1) / 2, 0))

    doc.units = ezunits.MM
    doc.saveas(out_path)
    return src_w * faktor, src_h * faktor
```

- [ ] **Step 4: Ekspor dari paket**

Tambahkan ke `prep/__init__.py` — import dari `.passthrough` dan tambahkan `"read_size"`, `"plt_to_polylines"`, `"scale_to_dxf"` ke `__all__`, mengikuti pola yang sudah ada di berkas itu.

- [ ] **Step 5: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.passthrough
docker compose run --rm --no-deps laser-prep python -c "import prep; print(prep.read_size, prep.scale_to_dxf)"
```

Diharapkan: `ok`, lalu dua nama fungsi tercetak.

- [ ] **Step 6: Commit**

```bash
git add prep/passthrough.py prep/__init__.py
git commit -m "feat(passthrough): baca ukuran DXF/PLT dan skalakan jadi DXF mm"
```

---

### Task 7: Sambungkan passthrough ke `app.py`

**Files:**
- Modify: `app.py` (import, parameter `scale_passthrough`, ganti cabang `PASSTHROUGH_EXT`)
- Modify: `selfcheck.py` (tambah `scale_passthrough=False` ke default `_call`, tiga cek baru)

**Interfaces:**
- Consumes: `read_size`, `scale_to_dxf` dari Task 6; parameter `rotate` dari Task 2.
- Produces: parameter form `scale_passthrough: bool` pada `POST /process`; balasan passthrough kini memuat `size_mm` (sebelumnya `null`) — dipakai UI di Task 8/9.

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan `scale_passthrough=False` ke dict default `_call`. Tambahkan tiga cek:

```python
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


def check_plt_size() -> None:
    """PLT: 4000 x 2000 satuan plotter = 100 x 50 mm."""
    plt = b"IN;SP1;PU0,0;PD4000,0;PD4000,2000;PU;"
    d = _call(file=_upload("p.plt", io.BytesIO(plt)), job="vector", width_mm=40.0)
    assert d["ok"], d
    assert d["passthrough"] is True, d
    w, h = d["size_mm"]
    assert abs(w - 100.0) < 0.05 and abs(h - 50.0) < 0.05, d["size_mm"]


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
```

Daftarkan ketiganya di `__main__` setelah `check_zip()`.

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `TypeError: process() got an unexpected keyword argument 'scale_passthrough'`.

- [ ] **Step 3: Implementasi**

Di `app.py`, tambahkan ke import dari `prep`:

```python
    read_size,
    scale_to_dxf,
```

Tambahkan parameter setelah `rotate: int = Form(0),`:

```python
    scale_passthrough: bool = Form(False),   # DXF/PLT hanya diskalakan bila diminta
```

**Ganti** seluruh cabang `elif ext in PASSTHROUGH_EXT:` yang ada dengan:

```python
            elif ext in PASSTHROUGH_EXT:
                if scale_passthrough:
                    out_dxf = os.path.join(sess_dir, f"{stem}_scaled.dxf")
                    size = scale_to_dxf(
                        src_path, out_dxf,
                        target_width_mm=width_mm,
                        target_height_mm=target_h,
                        rotate=rotate,
                    )
                    peringatan = []
                    if ext == ".plt":
                        peringatan.append(
                            "PLT yang diskalakan keluar sebagai DXF — EZCAD2 membacanya "
                            "sama baiknya, dan geometrinya sudah dipusatkan di (0,0)."
                        )
                    if mirror:
                        peringatan.append(
                            "Cermin TIDAK diterapkan pada berkas DXF/PLT. Bila perlu "
                            "dicermin, cermin objeknya di EZCAD2 setelah import."
                        )
                    return JSONResponse({
                        "ok": True, "job": job, "passthrough": False,
                        "downloads": [{"label": "DXF terskala (mm)", "url": url(out_dxf)}],
                        "before": None, "after": None,
                        "size_mm": [round(size[0], 2), round(size[1], 2)],
                        "n_paths": None,
                        "warnings": peringatan,
                    })

                # Tidak diskalakan: berkas disajikan APA ADANYA — itulah gunanya
                # passthrough. Yang berubah hanyalah alat kini memberi tahu ukurannya.
                w_mm, h_mm, peringatan = read_size(src_path)
                peringatan = list(peringatan)
                peringatan.append(
                    f"File {ext.upper().lstrip('.')} disalin apa adanya, ukuran asli "
                    f"{w_mm:.1f} × {h_mm:.1f} mm. Tekan “Skalakan ke ukuran target” "
                    f"bila ukurannya perlu diubah."
                )
                if rotate:
                    peringatan.append(
                        "Putaran diabaikan untuk berkas yang lewat apa adanya. "
                        "Tekan “Skalakan ke ukuran target” bila putarannya perlu diterapkan."
                    )
                return JSONResponse({
                    "ok": True, "job": job, "passthrough": True,
                    "downloads": [{"label": ext.upper().lstrip("."), "url": url(src_path)}],
                    "before": None, "after": None,
                    "size_mm": [round(w_mm, 2), round(h_mm, 2)],
                    "n_paths": None,
                    "warnings": peringatan,
                })
```

Galat dari `read_size`/`scale_to_dxf` (`ValueError`) sudah tertangkap penangan `except Exception` yang ada di ujung `process()` dan dibalas sebagai `{"ok": false, "error": ...}` — tidak perlu penanganan tambahan.

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Diharapkan: `selfcheck ok`. Jumlah cek kini 19 — spec menyebut 17 karena saat
ditulis `check_rotate_size_swap` dan `check_batch_budget` belum terpikir. Cek
tambahan tidak perlu ruling; yang dilarang adalah cek yang HILANG.

- [ ] **Step 5: Commit**

```bash
git add app.py selfcheck.py
git commit -m "feat: laporkan ukuran DXF/PLT, skalakan hanya bila diminta"
```

---

### Task 8: UI — batch, baris hasil per file, tombol ZIP

Seluruhnya di `templates/index.html`. Tidak ada cek otomatis; verifikasi lewat browser dengan langkah yang disebutkan.

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: parameter form `reset` (Task 4), endpoint `POST /zip` (Task 5), bentuk balasan `/process` yang sudah ada.
- Produces: fungsi JS `renderRow(d, namaFile)` dan variabel `hasilNama` (array nama berkas hasil) — dipakai Task 9 untuk menambahkan kotak area kerja.

- [ ] **Step 1: Input banyak berkas**

- Tambahkan atribut `multiple` pada `<input type="file" id="file" hidden />`.
- Ubah `picked` dari satu berkas jadi array: `let picked = [];`
- Ganti penangan drop dan `onchange` agar mengambil seluruh berkas:
  `drop.addEventListener("drop", e => { if (e.dataTransfer.files.length) setFiles([...e.dataTransfer.files]); });`
  dan `fileInput.onchange = e => { if (e.target.files.length) setFiles([...e.target.files]); };`
- Ganti `setFile(f)` jadi `setFiles(fs)`: simpan array, tulis `drop.querySelector("b").textContent` jadi `"📄 " + fs[0].name` bila satu berkas, atau `"📄 " + fs.length + " berkas"` bila lebih; aktifkan tombol; kosongkan `#result` dengan pesan "Tekan Proses untuk memulai".
  Pratinjau instan sebelum diproses dihapus untuk banyak berkas — untuk satu berkas boleh dipertahankan seperti sekarang.

- [ ] **Step 2: Gelung batch pada tombol Proses**

Ganti isi `$("#go").onclick` sehingga:

```js
$("#go").onclick = async () => {
  if (!picked.length) return;
  const btn = $("#go"); btn.disabled = true;
  $("#result").innerHTML = "";
  hasilNama = [];
  let sukses = 0;
  for (let i = 0; i < picked.length; i++) {
    btn.innerHTML = '<span class="spin"></span>Memproses ' + (i + 1) + ' dari ' + picked.length + '…';
    const fd = bacaSetelanKeFormData();       // dipakai bersama; lihat Task 9
    fd.append("file", picked[i]);
    fd.append("reset", i === 0);              // hanya file pertama mengosongkan folder sesi
    let data;
    try {
      const res = await fetch("/process", { method: "POST", body: fd });
      data = await res.json();
    } catch (err) {
      data = { ok: false, error: "Gagal menghubungi server: " + err };
    }
    // Satu file gagal TIDAK menghentikan batch — barisnya merah, sisanya lanjut.
    $("#result").insertAdjacentHTML("beforeend", renderRow(data, picked[i].name));
    if (data.ok) sukses++;
  }
  segarkanHasilNama();
  if (sukses > 1) $("#result").insertAdjacentHTML("beforeend", tombolZip());
  btn.disabled = false; btn.textContent = "Proses";
};
```

Untuk tahap ini, `bacaSetelanKeFormData()` boleh berupa pemindahan langsung dari kode `fd.append(...)` yang sekarang ada di dalam `onclick` — Task 9 yang menyatukannya dengan preset.

- [ ] **Step 3: `renderRow` menggantikan `render`**

Ganti seluruh fungsi `render(d)` dengan:

```js
// Mengembalikan STRING, tidak menulis ke #result: gelung batch yang
// menempelkannya satu per satu, dan tombol "Skalakan" mengganti satu baris saja.
function renderRow(d, namaFile) {
  let html = '<div class="row-hasil" data-nama="' + namaFile + '">';
  html += '<div class="row-judul">' + namaFile + '</div>';
  if (!d.ok) {
    return html + '<div class="err">Error: ' + (d.error || "tidak diketahui") + '</div></div>';
  }
  if (!d.passthrough) {
    html += '<div class="previews">';
    html += '<div class="pv"><h3>Sebelum</h3><div class="imgbox">'
          + (d.before ? '<img src="' + d.before + '">' : '—') + '</div></div>';
    html += '<div class="pv"><h3>Sesudah (siap EZCAD2)</h3><div class="imgbox sesudah">'
          + (d.after ? '<img src="' + d.after + '">' : '—') + '</div></div>';
    html += '</div>';
  }
  html += '<div class="meta">';
  if (d.size_mm) html += '<span class="chip">Ukuran: <b>' + d.size_mm[0] + ' × ' + d.size_mm[1] + ' mm</b></span>';
  if (d.n_paths != null) html += '<span class="chip">Kontur: <b>' + d.n_paths + '</b></span>';
  html += '<span class="chip">Mode: <b>' + (d.job === "vector" ? "Vektor (DXF)" : "Grayscale (PNG)") + '</b></span>';
  html += '</div>';
  html += '<div class="dl">';
  d.downloads.forEach((x, i) => {
    html += '<a class="' + (i > 0 ? "sec" : "") + '" href="' + x.url + '" download>⬇ ' + x.label + '</a>';
  });
  if (d.passthrough) html += '<button class="skala">Skalakan ke ukuran target</button>';
  html += '</div>';
  if (d.warnings && d.warnings.length) {
    html += '<div class="warns">';
    d.warnings.forEach(w => { html += '<div class="warn">⚠ ' + w + '</div>'; });
    html += '</div>';
  }
  return html + '</div>';
}
```

Tambahkan CSS bersama aturan lain di `<style>`:

```css
.row-hasil{border-top:1px solid var(--line);padding-top:14px;margin-top:14px}
.row-hasil:first-child{border-top:none;padding-top:0;margin-top:0}
.row-judul{font-size:13px;color:var(--muted);margin-bottom:10px;word-break:break-all}
.skala{background:var(--panel2);border:1px solid var(--line);color:var(--text);padding:10px 14px;border-radius:9px;font-size:14px;font-weight:600;cursor:pointer}
```

- [ ] **Step 4: Tombol ZIP**

```js
function tombolZip() {
  return '<div class="dl"><button class="go" id="zip" style="width:auto">⬇ Unduh semua (ZIP)</button></div>';
}

// Dibaca ulang dari DOM, bukan diakumulasi manual: tombol "Skalakan" mengganti
// satu baris dan mengubah nama berkasnya, dan mencocokkan nama lama secara
// tekstual tidak bisa diandalkan — server menyanitasi nama lalu menempelkan
// 6 hex acak (_safe_stem), jadi nama di klien tidak sama dengan nama di server.
function segarkanHasilNama() {
  hasilNama = [...document.querySelectorAll("#result .dl a[download]")]
    .map(a => a.getAttribute("href").split("?")[0].split("/").pop());
}
```

Pasang penangannya lewat delegasi pada `#result` (baris dibuat setelah skrip berjalan, jadi `onclick` langsung tidak akan terpasang):

```js
$("#result").addEventListener("click", async e => {
  if (e.target.id !== "zip") return;
  const res = await fetch("/zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names: hasilNama }),
  });
  if (!res.ok) { alert("Gagal membuat ZIP."); return; }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "laser-prep.zip";
  a.click();
  URL.revokeObjectURL(a.href);
});
```

Deklarasikan `let hasilNama = [];` bersama variabel global lain di atas.

- [ ] **Step 5: Tombol "Skalakan ke ukuran target"**

Tambahkan di dalam delegasi klik `#result` yang sama, sebelum penanganan `#zip`:

```js
  if (e.target.classList.contains("skala")) {
    const baris = e.target.closest(".row-hasil");
    const nama = baris.dataset.nama;
    const berkas = picked.find(f => f.name === nama);
    if (!berkas) { alert("Berkas sumber tak ada lagi — unggah ulang."); return; }
    e.target.disabled = true; e.target.textContent = "Menskalakan…";
    const fd = bacaSetelanKeFormData();
    fd.append("file", berkas);
    fd.append("scale_passthrough", "true");
    fd.append("reset", "false");           // jangan menghapus hasil batch lainnya
    let data;
    try {
      data = await (await fetch("/process", { method: "POST", body: fd })).json();
    } catch (err) {
      data = { ok: false, error: "Gagal menghubungi server: " + err };
    }
    baris.outerHTML = renderRow(data, nama);
    segarkanHasilNama();     // nama hasil berubah jadi …_scaled.dxf
    return;
  }
```

Pastikan penangan delegasi dideklarasikan `async` (`$("#result").addEventListener("click", async e => {…})`).

- [ ] **Step 6: Verifikasi di browser**

```bash
docker compose up -d
```

Buka `http://127.0.0.1:8000` dan periksa satu per satu:

1. Seret **tiga** gambar sekaligus → tombol menampilkan "Memproses 1 dari 3…", "2 dari 3…", "3 dari 3…".
2. Tiga baris hasil muncul, masing-masing dengan pratinjau, chip ukuran, dan tautan unduh sendiri.
3. Tombol "⬇ Unduh semua (ZIP)" muncul; ditekan → berkas ZIP terunduh dan berisi tiga berkas hasil.
4. Ulangi dengan **satu** gambar → satu baris, TIDAK ada tombol ZIP.
5. Unggah satu berkas rusak (mis. `.png` berisi teks acak) bersama dua gambar sah → baris rusak jadi merah, dua lainnya tetap selesai.
6. Unggah satu `.dxf` → baris menampilkan ukuran asli dan tombol "Skalakan ke ukuran target"; ditekan → baris berganti jadi hasil terskala dengan tautan `_scaled.dxf`.
7. Konsol browser bersih (tanpa `Uncaught`).

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): batch banyak berkas, baris hasil per file, unduh ZIP"
```

---

### Task 9: UI — preset, daftar lensa, kotak area kerja, dropdown putar

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `renderRow(d, namaFile)` dan `hasilNama` dari Task 8; parameter form `rotate` dari Task 2.
- Produces: `bacaSetelan()` / `tulisSetelan(obj)` / `bacaSetelanKeFormData()`.

- [ ] **Step 1: Dropdown putar**

Tambahkan di bawah baris "Lebar target / Tinggi maks" (berlaku untuk kedua mode, jadi di luar kedua `.opts`):

```html
<label>Putar</label>
<select id="rotate">
  <option value="0">0° (tanpa putar)</option>
  <option value="90">90° searah jarum jam</option>
  <option value="180">180°</option>
  <option value="270">270° (90° berlawanan jarum jam)</option>
</select>
<div class="hint">Diterapkan sebelum penskalaan, jadi "lebar target" selalu merujuk lebar hasil akhir. Bila cermin juga menyala, putaran dilakukan lebih dulu.</div>
```

- [ ] **Step 2: `bacaSetelan()` / `tulisSetelan()`**

Ganti pembangunan `FormData` yang tersebar dengan satu sumber kebenaran:

```js
// Satu daftar nama kontrol untuk SEMUA pemakainya. Sebelum ini, submit dan
// preset akan punya daftar masing-masing, dan salah satunya pasti ketinggalan
// begitu ada kontrol baru.
const KONTROL_ANGKA = ["width_mm", "height_mm", "rotate", "threshold", "filter_speckle", "dpi", "gamma"];
const KONTROL_CENTANG = ["auto_threshold", "invert", "mirror_vector", "autocontrast",
                         "autotrim", "clahe", "invert_gray", "mirror_gray", "remove_bg"];

function bacaSetelan() {
  const o = { job };
  KONTROL_ANGKA.forEach(k => o[k] = $("#" + k).value);
  KONTROL_CENTANG.forEach(k => o[k] = $("#" + k).checked);
  return o;
}

function tulisSetelan(o) {
  if (o.job) pilihMode(o.job);          // fungsi yang dipakai tombol mode
  KONTROL_ANGKA.forEach(k => { if (o[k] !== undefined) $("#" + k).value = o[k]; });
  KONTROL_CENTANG.forEach(k => { if (o[k] !== undefined) $("#" + k).checked = o[k]; });
  $("#thrbox").style.display = $("#auto_threshold").checked ? "none" : "block";
}

function bacaSetelanKeFormData() {
  const o = bacaSetelan(), fd = new FormData();
  fd.append("job", o.job);
  fd.append("width_mm", o.width_mm || "40");
  fd.append("height_mm", o.height_mm || "0");
  fd.append("rotate", o.rotate || "0");
  if (o.job === "vector") {
    fd.append("auto_threshold", o.auto_threshold);
    fd.append("threshold", o.threshold || "128");
    fd.append("invert", o.invert);
    fd.append("mirror", o.mirror_vector);
    fd.append("filter_speckle", o.filter_speckle || "4");
  } else {
    fd.append("dpi", o.dpi || "600");
    fd.append("gamma", o.gamma || "1.0");
    fd.append("autocontrast", o.autocontrast);
    fd.append("clahe", o.clahe);
    fd.append("invert", o.invert_gray);
    fd.append("mirror", o.mirror_gray);
    fd.append("autotrim", o.autotrim);
    fd.append("remove_bg", o.remove_bg);
  }
  return fd;
}
```

Ekstrak logika tombol mode yang ada jadi `function pilihMode(j)` supaya `tulisSetelan` bisa memanggilnya, dan panggil `pilihMode(b.dataset.job)` dari penangan klik tombol.

- [ ] **Step 3: Preset di localStorage**

Tambahkan baris kontrol di atas pemilih mode:

```html
<h2>Preset</h2>
<div class="row">
  <div><select id="preset"><option value="">— pilih preset —</option></select></div>
  <div style="flex:0 0 auto"><button class="seg-btn" id="preset_simpan">Simpan</button>
  <button class="seg-btn" id="preset_hapus">Hapus</button></div>
</div>
```

JS:

```js
const PRESET_KEY = "lp_presets";
const ambilPreset = () => JSON.parse(localStorage.getItem(PRESET_KEY) || "{}");
const simpanPreset = o => localStorage.setItem(PRESET_KEY, JSON.stringify(o));

function isiDaftarPreset(terpilih) {
  const p = ambilPreset();
  $("#preset").innerHTML = '<option value="">— pilih preset —</option>'
    + Object.keys(p).sort().map(n => '<option>' + n + '</option>').join("");
  if (terpilih) $("#preset").value = terpilih;
}
$("#preset").onchange = e => { const p = ambilPreset()[e.target.value]; if (p) tulisSetelan(p); };
$("#preset_simpan").onclick = () => {
  const nama = (prompt("Nama preset:", $("#preset").value || "") || "").trim();
  if (!nama) return;
  const p = ambilPreset();
  if (p[nama] && !confirm('Preset "' + nama + '" sudah ada. Timpa?')) return;
  p[nama] = bacaSetelan(); simpanPreset(p); isiDaftarPreset(nama);
};
$("#preset_hapus").onclick = () => {
  const nama = $("#preset").value;
  if (!nama || !confirm('Hapus preset "' + nama + '"?')) return;
  const p = ambilPreset(); delete p[nama]; simpanPreset(p); isiDaftarPreset("");
};
isiDaftarPreset("");
```

- [ ] **Step 4: Daftar lensa**

```html
<label>Area kerja (lensa)</label>
<div class="row">
  <div><select id="field"></select></div>
  <div style="flex:0 0 auto"><button class="seg-btn" id="field_tambah">＋</button>
  <button class="seg-btn" id="field_hapus">−</button></div>
</div>
<div class="hint">Kotak garis putus-putus pada pratinjau "Sesudah" memakai ukuran lensa ini.</div>
```

```js
const FIELD_KEY = "lp_fields", FIELD_SEL = "lp_field_sel";
const FIELD_AWAL = [{ nama: "F110", w: 70, h: 70 }, { nama: "F163", w: 110, h: 110 }];
const ambilField = () => JSON.parse(localStorage.getItem(FIELD_KEY) || "null") || FIELD_AWAL;
const simpanField = a => localStorage.setItem(FIELD_KEY, JSON.stringify(a));

function isiDaftarField() {
  const a = ambilField();
  $("#field").innerHTML = a.map(f => '<option>' + f.nama + ' — ' + f.w + ' × ' + f.h + ' mm</option>').join("");
  const s = localStorage.getItem(FIELD_SEL);
  if (s !== null && a[s]) $("#field").selectedIndex = Number(s);
}
const fieldTerpilih = () => ambilField()[$("#field").selectedIndex] || FIELD_AWAL[1];
$("#field").onchange = () => localStorage.setItem(FIELD_SEL, $("#field").selectedIndex);
$("#field_tambah").onclick = () => {
  const nama = (prompt("Nama lensa (mis. F254):") || "").trim(); if (!nama) return;
  const w = parseFloat(prompt("Lebar area kerja (mm):") || "0");
  const h = parseFloat(prompt("Tinggi area kerja (mm):") || "0");
  if (!(w > 0 && h > 0)) { alert("Ukuran tidak sah."); return; }
  const a = ambilField(); a.push({ nama, w, h }); simpanField(a); isiDaftarField();
};
$("#field_hapus").onclick = () => {
  const a = ambilField();
  if (a.length <= 1) { alert("Sisakan minimal satu lensa."); return; }
  if (!confirm("Hapus " + a[$("#field").selectedIndex].nama + "?")) return;
  a.splice($("#field").selectedIndex, 1); simpanField(a);
  localStorage.setItem(FIELD_SEL, 0); isiDaftarField();
};
isiDaftarField();
```

- [ ] **Step 5: Kotak area kerja di pratinjau "Sesudah"**

Di dalam `renderRow`, saat `d.size_mm` ada, bungkus isi panel "Sesudah" dengan:

```js
function kotakField(d) {
  const f = fieldTerpilih(), [w, h] = d.size_mm;
  const lewat = w > f.w + 0.05 || h > f.h + 0.05;
  const isi = d.after
    ? '<img src="' + d.after + '" style="width:100%;height:100%;object-fit:fill">'
    : '<div class="jejak"></div>';       // DXF: tidak ada gambar, hanya jejak-kaki
  return '<div class="field-box' + (lewat ? ' lewat' : '') + '" '
       + 'style="aspect-ratio:' + f.w + '/' + f.h + '">'
       + '<div class="artwork" style="width:' + Math.min(100, w / f.w * 100) + '%;'
       + 'height:' + Math.min(100, h / f.h * 100) + '%">' + isi + '</div></div>'
       + (lewat ? '<div class="warn">⚠ Lebih besar dari area kerja ' + f.nama
                + ' (' + f.w + ' × ' + f.h + ' mm).</div>' : '');
}
```

CSS pendamping (gaya mengikuti berkas yang ada):

```css
.field-box{position:relative;width:100%;background:#fff;border:1.5px dashed var(--line);border-radius:8px;display:flex;align-items:center;justify-content:center}
.field-box.lewat{border-color:#7a2626}
.field-box .artwork{display:flex;align-items:center;justify-content:center;overflow:hidden}
.jejak{width:100%;height:100%;background:repeating-linear-gradient(45deg,#d9dee8,#d9dee8 4px,#fff 4px,#fff 8px);border:1px solid #98a1b3}
```

**Ganti** blok `if (!d.passthrough) { … }` di dalam `renderRow` dengan blok berikut. Syaratnya berubah jadi `d.size_mm`, bukan `!d.passthrough`: DXF/PLT justru berkas yang paling butuh kotak area kerja, dan sekarang ukurannya sudah dilaporkan.

```js
  if (d.size_mm) {
    html += '<div class="previews">';
    html += '<div class="pv"><h3>Sebelum</h3><div class="imgbox">'
          + (d.before ? '<img src="' + d.before + '">'
                      : '<span class="empty">berkas vektor — tanpa pratinjau gambar</span>')
          + '</div></div>';
    // Kedua tampilan ditulis sekaligus dan ditukar lewat kelas CSS. Dengan begitu
    // tombolnya tidak perlu menyimpan `d` atau merender ulang apa pun.
    html += '<div class="pv"><h3>Sesudah (siap EZCAD2) '
          + '<button class="pas">pas layar</button></h3>'
          + '<div class="imgbox">'
          + '<div class="tampil-field">' + kotakField(d) + '</div>'
          + '<div class="tampil-penuh">'
          + (d.after ? '<img src="' + d.after + '">' : '—') + '</div>'
          + '</div></div>';
    html += '</div>';
  }
```

CSS penukar tampilan:

```css
.row-hasil .tampil-field{width:100%}
.row-hasil .tampil-penuh{display:none}
.row-hasil.penuh .tampil-field{display:none}
.row-hasil.penuh .tampil-penuh{display:block}
.pv h3 .pas{float:right;background:var(--panel);border:1px solid var(--line);color:var(--muted);font-size:11px;padding:2px 8px;border-radius:999px;cursor:pointer;text-transform:none;letter-spacing:0}
```

Penangan tombol, di dalam delegasi klik `#result` dari Task 8:

```js
  if (e.target.classList.contains("pas")) {
    const baris = e.target.closest(".row-hasil");
    baris.classList.toggle("penuh");
    e.target.textContent = baris.classList.contains("penuh") ? "skala area kerja" : "pas layar";
    return;
  }
```

- [ ] **Step 6: Verifikasi di browser**

```bash
docker compose restart
```

Periksa:

1. Dropdown lensa berisi **F110 — 70 × 70 mm** dan **F163 — 110 × 110 mm**.
2. Proses gambar pada lebar 40 mm dengan F163 terpilih → kotak putus-putus muncul; artwork mengisi kira-kira 40/110 ≈ 36% lebarnya.
3. Ganti ke F110 lalu proses lagi → artwork mengisi 40/70 ≈ 57%.
4. Set lebar 200 mm dengan F110 → kotak jadi merah dan peringatan "Lebih besar dari area kerja F110" muncul, **tapi hasil tetap dibuat dan bisa diunduh**.
5. Tombol "pas layar" mengembalikan pratinjau ke tampilan penuh dan bisa dikembalikan lagi.
6. `＋` menambah lensa baru; muat ulang halaman → lensa itu masih ada.
7. Isi setelan apa saja → Simpan preset "uji" → ubah semua kontrol → pilih "uji" dari dropdown → **semua** kontrol kembali, termasuk mode.
8. Muat ulang halaman → preset "uji" masih ada di dropdown.
9. Putar 90° pada gambar potret → hasil benar-benar berputar searah jarum jam, dan chip ukuran menampilkan lebar/tinggi yang tertukar.
10. Konsol browser bersih.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): preset, daftar lensa, kotak area kerja, dropdown putar"
```

---

### Task 10: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Perbarui isi**

- Tambahkan **batch**: seret beberapa berkas sekaligus, setelan berlaku sama untuk semuanya, tombol "Unduh semua (ZIP)".
- Tambahkan **preset**: tersimpan di browser (localStorage), merekam seluruh setelan termasuk mode. Sebutkan bahwa preset hilang bila data situs browser dibersihkan.
- Tambahkan **area kerja**: daftar lensa bisa diedit, isi awal F110 (70 × 70 mm) dan F163 (110 × 110 mm); kotak putus-putus memperingatkan tapi tidak memblokir.
- Tambahkan **putar**: 0/90/180/270 searah jarum jam, diterapkan sebelum penskalaan dan sebelum cermin.
- Perbarui bagian **DXF/PLT**: alat kini melaporkan ukuran asli; penskalaan hanya terjadi bila tombolnya ditekan; PLT yang diskalakan keluar sebagai DXF; DXF tidak punya pratinjau gambar; cermin tidak diterapkan pada DXF/PLT.
- Tambahkan `prep/passthrough.py` ke pohon struktur berkas.
- Pastikan perintah selfcheck yang tertulis masih benar.

- [ ] **Step 2: Jalankan seluruh cek**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
docker compose run --rm --no-deps laser-prep python -m prep.geometry
docker compose run --rm --no-deps laser-prep python -m prep.vector
docker compose run --rm --no-deps laser-prep python -m prep.passthrough
```

Diharapkan: `selfcheck ok`, `ok`, `ok`, `ok`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: batch, preset, area kerja, putar, dan perilaku DXF/PLT"
```
