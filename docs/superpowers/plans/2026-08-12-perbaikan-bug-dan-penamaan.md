# Perbaikan Bug & Penamaan Berbasis Format — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perbaiki enam cacat terverifikasi di Laser Prep dan ganti nama dua cabang alat dari nama mesin (MOPA/UV) menjadi nama format output (Vektor/DXF, Grayscale/PNG).

**Architecture:** Berkas baru `selfcheck.py` di akar project memanggil fungsi endpoint `app.process()` langsung lewat `asyncio.run` — tanpa server HTTP dan tanpa dependensi tes. Cek dibangun lebih dulu (Task 1–3) supaya penggantian nama (Task 4) punya jaring pengaman yang membuktikan perubahan itu netral terhadap perilaku. Task 5 hanya prosa.

**Tech Stack:** Python 3.12, FastAPI, OpenCV (`opencv-python-headless`), Pillow, NumPy, vtracer, ezdxf, svgpathtools. Dijalankan lewat Docker Compose.

## Global Constraints

- **Tanpa dependensi baru.** `requirements.txt` tidak boleh bertambah. Tidak ada pytest, tidak ada httpx. Self-check memakai `assert` polos, mengikuti gaya `prep/vector.py:227-238`.
- **`cv2` tidak terpasang di host.** Semua perintah Python dijalankan di dalam container: `docker compose run --rm --no-deps laser-prep <perintah>`.
- **Bahasa.** Semua teks yang dilihat operator (label UI, hint, pesan error, warning) dan semua komentar/docstring ditulis dalam **Bahasa Indonesia**, mengikuti kode yang ada.
- **Nama mode yang disepakati, persis:** `Ke Vektor (DXF)` dan `Ke Grayscale (PNG)`.
- **Nilai `job` di API:** `"vector"` dan `"grayscale"`. Tanpa alias untuk nilai lama.
- **`EZCAD2` tetap disebut** di mana pun ia sudah muncul — itu software tujuan import, bukan jenis mesin.
- **Contoh material** (stainless, kaca) **tetap** di bagian README tentang *set pen parameter* — di situ ia instruksi operator, bukan nama fitur.
- **Komentar pembanding rembg di `prep/raster.py:31` tetap.** Komentar itu menjelaskan alasan memilih flood-fill; alasannya masih berlaku. Hanya UI dan README yang berhenti menyuruh install rembg.
- **Urutan tugas tidak boleh ditukar.** Task 4 (rename) bergantung pada cek yang dibangun Task 1–3.
- `python -m prep.vector` mengeluarkan `RuntimeWarning: 'prep.vector' found in sys.modules...` sebelum mencetak `ok`. Itu **normal** (karena `prep/__init__.py` mengimpor `prep.vector`) dan bukan kegagalan.

## Struktur Berkas

| Berkas | Tanggung jawab | Task |
|---|---|---|
| `selfcheck.py` *(baru)* | Cek end-to-end lewat `app.process()`. Satu fungsi `check_*` per cacat. | 1, 2, 3, 4 |
| `app.py` | Routing HTTP, wiring parameter ke `prep/`, penamaan `job`. | 1, 4 |
| `prep/raster.py` | Cabang grayscale + helper `_thumb`. | 2, 4, 5 |
| `prep/vector.py` | Cabang vektor. Buang param mati, betulkan preview SVG. | 3, 4 |
| `templates/index.html` | Label, hint, id elemen, nilai `job` yang dikirim. | 4, 5 |
| `README.md`, `requirements.txt` | Prosa & komentar. | 5 |

---

### Task 1: Self-check end-to-end + perbaikan invert grayscale

Bug #1: checkbox "Balik (negatif)" tidak berefek karena `app.py` tidak meneruskan `invert` ke `process_photo`.

**Files:**
- Create: `selfcheck.py`
- Modify: `app.py:157-161`

**Interfaces:**
- Consumes: `app.process()` — fungsi async endpoint, semua parameter keyword, mengembalikan `JSONResponse`. `app.OUT_DIR` — path folder hasil.
- Produces: helper di `selfcheck.py` yang dipakai Task 2–4:
  - `SID: str` — session id tetap, `"0" * 32`.
  - `_png_bytes(arr: np.ndarray) -> io.BytesIO`
  - `_upload(name: str, buf: io.BytesIO) -> UploadFile`
  - `_call(**kwargs) -> dict` — panggil `app.process()`, kembalikan body JSON sebagai dict.
  - `_out_path(url: str) -> str` — ubah URL `/out/<sid>/<berkas>` jadi path di disk.
  - `_cleanup() -> None`
  - `check_invert_grayscale() -> None`

- [ ] **Step 1: Tulis cek yang gagal**

Buat `selfcheck.py`:

```python
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
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `AssertionError: dengan invert seharusnya terang: {False: ~10.x, True: ~10.x}` — kedua nilai identik, membuktikan `invert` diabaikan.

- [ ] **Step 3: Perbaiki wiring**

Di `app.py`, pada pemanggilan `process_photo` (sekarang baris 157-161), tambahkan `invert=invert`:

```python
            r = process_photo(
                src_path, sess_dir, stem,
                target_width_mm=width_mm, dpi=int(dpi),
                remove_bg=remove_bg, autocontrast=autocontrast,
                clahe=clahe, gamma=float(gamma), invert=invert,
            )
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 5: Commit**

```bash
git add selfcheck.py app.py
git commit -m "fix: teruskan invert ke process_photo, tambah self-check end-to-end"
```

---

### Task 2: Preview pakai thumbnail, bukan berkas hasil penuh

Bug #2: `preview_after` menunjuk ke `png_path`, sehingga PNG resolusi penuh (bisa >12000 px) dikirim ke `<img>` di browser.

**Files:**
- Modify: `prep/raster.py:66` (nama berkas preview), `prep/raster.py:81-85` (blok thumbnail inline), `prep/raster.py:139-144` (penyimpanan hasil & nilai `preview_after`)
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: helper `_call`, `_out_path`, `_png_bytes`, `_upload` dari Task 1.
- Produces:
  - `prep.raster._thumb(img: np.ndarray, path: str, max_px: int = 900) -> None` — tulis thumbnail JPEG; menerima array BGR maupun grayscale.
  - `selfcheck.check_preview_thumb() -> None`
  - `RasterResult.preview_after` kini menunjuk berkas `{stem}_after.jpg`, bukan `png_path`.

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan ke `selfcheck.py`, tepat sebelum blok `if __name__ == "__main__":`:

```python
def check_preview_thumb() -> None:
    """bug #2: preview harus thumbnail; berkas download tetap resolusi penuh."""
    arr = np.full((1200, 1200), 128, np.uint8)
    arr[0:400, :] = 20
    d = _call(file=_upload("t.png", _png_bytes(arr)), width_mm=200.0, dpi=600)
    assert d["ok"], d
    for key in ("before", "after"):
        size = Image.open(_out_path(d[key])).size
        assert max(size) <= 900, f"preview '{key}' terlalu besar: {size}"
    full = Image.open(_out_path(d["downloads"][0]["url"])).size
    assert full[0] == 4724, f"berkas download harus resolusi penuh: {full}"
```

Ubah blok `__main__` menjadi:

```python
if __name__ == "__main__":
    try:
        check_invert_grayscale()
        check_preview_thumb()
    finally:
        _cleanup()
    print("selfcheck ok")
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `AssertionError: preview 'after' terlalu besar: (4724, 4724)`

- [ ] **Step 3: Tambahkan helper `_thumb`**

Di `prep/raster.py`, sisipkan fungsi ini tepat sebelum `def process_photo(`:

```python
def _thumb(img: np.ndarray, path: str, max_px: int = 900) -> None:
    """Tulis thumbnail JPEG untuk preview di browser.

    Preview cukup segini; berkas hasil resolusi penuh hanya untuk download —
    mengirim PNG 4000+ px ke <img> cuma bikin tab berat tanpa menambah informasi.
    """
    h, w = img.shape[:2]
    s = min(1.0, max_px / max(h, w))
    small = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1.0 else img
    cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 80])[1].tofile(path)
```

- [ ] **Step 4: Pakai helper untuk preview `before`**

Di `prep/raster.py`, ganti blok thumbnail inline (sekarang baris 81-85) menjadi:

```python
    _thumb(img, prev_before)
```

- [ ] **Step 5: Tulis preview `after` dan kembalikan path-nya**

Di `prep/raster.py`, tambahkan deklarasi path preview `after` di bawah `prev_before` (sekarang baris 66):

```python
    prev_after = os.path.join(out_dir, f"{stem}_after.jpg")
```

Ganti blok penyimpanan hasil (sekarang baris 139-140) menjadi:

```python
    # Simpan PNG grayscale dengan metadata DPI.
    Image.fromarray(out, mode="L").save(png_path, dpi=(dpi, dpi))
    _thumb(out, prev_after)
```

Lalu di blok `return RasterResult(`, ganti baris `preview_after=png_path,  # ...` menjadi:

```python
        preview_after=prev_after,
```

- [ ] **Step 6: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 7: Commit**

```bash
git add prep/raster.py selfcheck.py
git commit -m "fix: sajikan thumbnail untuk preview, bukan PNG hasil resolusi penuh"
```

---

### Task 3: Bersihkan `prep/vector.py`

Bug #5: parameter `despeckle` diterima lalu tidak pernah dipakai. Bug #6: panel "sebelum" untuk input SVG menampilkan gambar hasil, bukan berkas sumber.

**Files:**
- Modify: `prep/vector.py:37` , `prep/vector.py:147`, `prep/vector.py:159`, `prep/vector.py:220`
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: helper `_call`, `_upload` dari Task 1.
- Produces:
  - `prep.vector._preprocess_bitmap(src_path, work_png, threshold=128, auto_threshold=True, invert=False)` — parameter `despeckle` hilang.
  - `prep.vector.process_raster_logo(...)` — parameter `despeckle` hilang; sisanya tidak berubah.
  - `selfcheck.check_svg_preview_before() -> None`

- [ ] **Step 1: Tulis cek yang gagal**

Tambahkan ke `selfcheck.py`, tepat sebelum blok `if __name__ == "__main__":`:

```python
def check_svg_preview_before() -> None:
    """bug #6: untuk input SVG, panel 'sebelum' harus menunjuk SVG sumber, bukan hasil render."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<path d="M1,1 L9,1 L9,9 L1,9 Z"/></svg>')
    d = _call(file=_upload("s.svg", io.BytesIO(svg.encode())), job="mopa", width_mm=30.0)
    assert d["ok"], d
    assert ".svg" in d["before"], f"'sebelum' harus berkas SVG sumber: {d['before']}"
    # bandingkan path di disk, bukan URL: keduanya dapat cache-buster '?v=' yang berbeda
    # sehingga string URL-nya selalu tampak beda meski menunjuk berkas yang sama.
    assert _out_path(d["before"]) != _out_path(d["after"]), d
```

Tambahkan pemanggilannya di blok `__main__`, sehingga menjadi:

```python
if __name__ == "__main__":
    try:
        check_invert_grayscale()
        check_preview_thumb()
        check_svg_preview_before()
    finally:
        _cleanup()
    print("selfcheck ok")
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `AssertionError: 'sebelum' harus berkas SVG sumber: /out/000.../s_xxxxxx_after.png?v=...`

- [ ] **Step 3: Betulkan preview `before` untuk SVG**

Di `prep/vector.py`, dalam `return VectorResult(` milik `process_svg_input` (sekarang baris 220), ganti:

```python
        preview_before=prev_after,
```

menjadi:

```python
        preview_before=src_path,  # SVG sumber; browser bisa menampilkannya langsung di <img>
```

- [ ] **Step 4: Jalankan, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 5: Buang parameter `despeckle` yang mati**

Tiga perubahan di `prep/vector.py`:

1. Signature `_preprocess_bitmap` (sekarang baris 31-38) — hapus baris `despeckle: int = 2,` sehingga menjadi:

```python
def _preprocess_bitmap(
    src_path: str,
    work_png: str,
    threshold: int = 128,
    auto_threshold: bool = True,
    invert: bool = False,
) -> Tuple[int, List[str]]:
```

2. Signature `process_raster_logo` (sekarang baris 147) — hapus baris `despeckle: int = 2,`.

3. Pemanggilan (sekarang baris 158-160) — hapus argumen terakhir:

```python
    used_thr, warnings = _preprocess_bitmap(
        src_path, work_png, threshold, auto_threshold, invert
    )
```

- [ ] **Step 6: Jalankan kedua cek, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Expected: `ok` (didahului `RuntimeWarning` yang normal — lihat Global Constraints)

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok` — membuktikan tidak ada pemanggil yang masih mengirim `despeckle`.

- [ ] **Step 7: Commit**

```bash
git add prep/vector.py selfcheck.py
git commit -m "fix: preview 'sebelum' SVG pakai sumber, buang parameter despeckle yang mati"
```

---

### Task 4: Ganti nama cabang jadi berbasis format (kode)

Nama mesin (MOPA/UV) diganti nama format di seluruh kode. Cek dari Task 1–3 membuktikan perubahan ini netral terhadap perilaku.

**Files:**
- Modify: `app.py:5-6` (docstring), `app.py:79` (komentar `job`), `app.py:113`, `app.py:135`, `app.py:153`, `app.py:155`
- Modify: `templates/index.html:67-68`, `:70`, `:74`, `:82-83`, `:98-99`, `:115`, `:135`, `:143-146`, `:180`, `:190`, `:217`
- Modify: `prep/vector.py:2`, `prep/raster.py:2` (docstring), `prep/raster.py:65` (nama berkas output)
- Modify: `selfcheck.py`

**Interfaces:**
- Consumes: seluruh fungsi `check_*` dari Task 1–3.
- Produces: nilai `job` yang sah kini **hanya** `"vector"` dan `"grayscale"`. Berkas hasil grayscale bernama `{stem}_grayscale.png`.

- [ ] **Step 1: Ubah cek supaya memakai nama baru — pastikan GAGAL**

Di `selfcheck.py`, ubah default `job` di `_call` dari `"uv"` menjadi `"grayscale"`:

```python
    args = dict(
        lp_sid=SID, job="grayscale", width_mm=20.0,
        auto_threshold=True, threshold=128, invert=False, filter_speckle=4,
        dpi=100, remove_bg=False, autocontrast=True, clahe=False, gamma=1.0,
    )
```

Di `check_svg_preview_before`, ubah `job="mopa"` menjadi `job="vector"`.

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `fastapi.exceptions.HTTPException: 400: Job tidak dikenal.` — bukan `AssertionError`. `process()` melempar `HTTPException` ketimbang mengembalikan `JSONResponse` untuk job tak dikenal, jadi `_call` ikut melempar. Ini kegagalan yang benar: membuktikan `app.py` belum mengenal nama baru.

- [ ] **Step 2: Ganti nama di `app.py`**

Ganti docstring baris 5-6 menjadi:

```python
- Mode "Ke Vektor (DXF)": JPG/PNG/SVG -> DXF + SVG bersih, skala mm benar.
- Mode "Ke Grayscale (PNG)": foto -> PNG grayscale bersih, ukuran fisik benar.
```

Ganti komentar pada parameter `job` (baris 79):

```python
    job: str = Form(...),                 # "vector" | "grayscale"
```

Ganti empat tempat di badan `process()`:

| Sekarang | Menjadi |
|---|---|
| `if job == "mopa":` | `if job == "vector":` |
| `raise HTTPException(400, f"Format {ext} tak didukung untuk cabang MOPA.")` | `raise HTTPException(400, f"Format {ext} tak didukung untuk mode Vektor.")` |
| `elif job == "uv":` | `elif job == "grayscale":` |
| `raise HTTPException(400, f"Cabang Kaca UV butuh gambar raster (JPG/PNG/...). Dapat: {ext}")` | `raise HTTPException(400, f"Mode Grayscale butuh gambar raster (JPG/PNG/TIFF). Dapat: {ext}")` |

- [ ] **Step 3: Jalankan cek, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

- [ ] **Step 4: Ganti nama berkas output grayscale**

Di `prep/raster.py` baris 65:

```python
    png_path = os.path.join(out_dir, f"{stem}_grayscale.png")
```

Ganti docstring `prep/raster.py:2`:

```python
Mode KE GRAYSCALE (PNG): foto/gambar -> PNG grayscale bersih dengan ukuran fisik benar.
```

Ganti docstring `prep/vector.py:2`:

```python
Mode KE VEKTOR (DXF): logo raster (JPG/PNG) -> vektor bersih -> DXF + SVG + preview.
```

- [ ] **Step 5: Jalankan cek, pastikan LULUS**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok` (cek memakai URL dari respons, bukan nama berkas yang di-hardcode, jadi penggantian nama tidak merusaknya)

- [ ] **Step 6: Ganti label dan id di `templates/index.html`**

Tombol pemilih mode (baris 67-68):

```html
      <button data-job="vector" class="active">Ke Vektor<br><small>(DXF)</small></button>
      <button data-job="grayscale">Ke Grayscale<br><small>(PNG)</small></button>
```

Hint di bawahnya (baris 70):

```html
    <div class="hint"><b>Ke Vektor (DXF)</b>: ubah logo/gambar jadi garis kontur (DXF + SVG), ukuran mm tepat. <b>Ke Grayscale (PNG)</b>: ubah foto jadi PNG abu-abu, ukuran fisik mm pada DPI yang benar.</div>
```

`dropinfo` (baris 74):

```html
      <div class="hint" id="dropinfo">Vektor: JPG, PNG, SVG, DXF · Grayscale: JPG, PNG, TIFF</div>
```

Komentar & id blok opsi (baris 82-83 dan 98-99):

```html
    <!-- opsi mode Vektor -->
    <div class="opts" id="opts-vector">
```

```html
    <!-- opsi mode Grayscale -->
    <div class="opts" id="opts-grayscale" style="display:none">
```

Checkbox invert grayscale (baris 115) — ganti id `invert_uv` menjadi `invert_gray`:

```html
      <label class="check"><input type="checkbox" id="invert_gray" /> Balik (negatif)</label>
```

- [ ] **Step 7: Ganti JavaScript di `templates/index.html`**

Baris 135:

```javascript
let job = "vector";
```

Blok pemilih mode (baris 143-146):

```javascript
    $("#opts-vector").style.display = job==="vector"?"block":"none";
    $("#opts-grayscale").style.display = job==="grayscale"?"block":"none";
    $("#dropinfo").textContent = job==="vector"
      ? "Vektor: JPG, PNG, SVG, DXF" : "Grayscale: JPG, PNG, TIFF";
```

Cabang pengiriman form (baris 180):

```javascript
  if(job==="vector"){
```

Pengiriman invert grayscale (baris 190):

```javascript
    fd.append("invert",$("#invert_gray").checked);
```

Chip "Mode" pada hasil (baris 217):

```javascript
  html+='<span class="chip">Mode: <b>'+(d.job==="vector"?"Vektor (DXF)":"Grayscale (PNG)")+'</b></span>';
```

- [ ] **Step 8: Verifikasi UI di browser**

```bash
docker compose up -d
```

Buka `http://127.0.0.1:8000` lalu periksa satu per satu:

1. Dua tombol berbunyi **Ke Vektor (DXF)** dan **Ke Grayscale (PNG)**.
2. Menekan tiap tombol menukar blok opsi (threshold/speckle vs DPI/gamma) dan mengubah teks daftar format di kotak upload.
3. Unggah `samples/logo.jpg` pada mode Vektor, tekan **Proses** — preview "sebelum" dan "sesudah" keduanya tampil, tautan DXF dan SVG bisa diunduh, chip Mode berbunyi `Vektor (DXF)`.
4. Unggah `samples/photo.png` pada mode Grayscale, tekan **Proses** — preview tampil, chip Mode berbunyi `Grayscale (PNG)`, berkas unduhan bernama berakhiran `_grayscale.png`.
5. Centang **Balik (negatif)**, tekan **Proses** lagi — preview "sesudah" kini negatif. (Ini bug #1 dilihat dari sisi operator.)

```bash
docker compose down
```

- [ ] **Step 9: Commit**

```bash
git add app.py prep/raster.py prep/vector.py templates/index.html selfcheck.py
git commit -m "refactor: ganti nama cabang MOPA/UV jadi Vektor (DXF) / Grayscale (PNG)"
```

---

### Task 5: Dokumentasi & teks yang menyesatkan

Bug #3 (docstring mengklaim fitur yang tidak ada) dan bug #4 (UI + README menyuruh install rembg yang sudah dihapus), plus sisa penyebutan nama mesin di prosa.

**Files:**
- Modify: `prep/raster.py:4`
- Modify: `templates/index.html:117-118`
- Modify: `requirements.txt:11`
- Modify: `README.md` — baris 30-33, 45-49, 66, 71, 75, 79, 83, 87, 120-121

**Interfaces:**
- Consumes: nama mode dari Task 4.
- Produces: tidak ada antarmuka kode. Task terakhir.

- [ ] **Step 1: Hapus klaim fitur yang tidak ada di docstring**

Di `prep/raster.py` baris 4, hapus `crop/auto-trim` (auto-trim belum ada kodenya):

```python
Python menyiapkan: grayscale, kontras, penskalaan ke mm @ DPI.
```

- [ ] **Step 2: Perbaiki label & hint hapus background**

Di `templates/index.html`, ganti baris 117-118:

```html
      <label class="check"><input type="checkbox" id="remove_bg" /> Hapus background polos</label>
      <div class="hint">Latar seragam yang menyambung dari tepi dijadikan putih. Teks tetap aman. Untuk foto berlatar ramai efeknya minim.</div>
```

- [ ] **Step 3: Perbaiki komentar `requirements.txt`**

Ganti baris 11-12:

```
# Hapus background pada mode Grayscale memakai flood-fill warna (built-in, tanpa model).
# rembg tak lagi diperlukan.
```

- [ ] **Step 4: Perbarui README**

Tabel "Dua cabang" (baris 30-33) — ganti judul bagian, nama cabang, kolom **Untuk**, dan hapus kata `crop`:

```markdown
## Dua mode

| Mode | Untuk | Input | Output | Yang dikerjakan Python |
|---|---|---|---|---|
| **Ke Vektor (DXF)** | Ukiran garis / kontur | JPG, PNG, SVG, (DXF/PLT passthrough) | **DXF** (mm) + SVG | Bersihkan bitmap, vektorisasi (vtracer), buang speckle, skala mm presisi |
| **Ke Grayscale (PNG)** | Ukiran bernada abu-abu | JPG, PNG, TIFF | **PNG grayscale** (DPI benar) | Grayscale, auto-kontras/CLAHE, gamma, skala fisik mm @ DPI |
```

Langkah instalasi (baris 45-49) — hapus seluruh langkah opsional rembg, sehingga daftar berhenti di langkah 2 (`pip install -r requirements.txt`).

Langkah pemakaian baris 66 dan 71:

```markdown
1. Pilih **mode** (Ke Vektor (DXF), atau Ke Grayscale (PNG)).
```

```markdown
6. **Download** hasilnya (DXF untuk mode Vektor, PNG untuk mode Grayscale).
```

Judul bagian import baris 75 dan 83 — isi langkah di bawahnya **tidak berubah**, termasuk contoh material pada langkah *set pen parameter*:

```markdown
**Import DXF:**
```

```markdown
**Import PNG grayscale:**
```

Komentar pohon struktur project (baris 120-121):

```
│   ├── vector.py          # mode Ke Vektor: raster/SVG → DXF + SVG
│   └── raster.py          # mode Ke Grayscale: foto → PNG grayscale (skala mm @ DPI)
```

Tambahkan `selfcheck.py` ke pohon struktur, tepat di bawah baris `├── README.md`:

```
├── selfcheck.py           # cek end-to-end: docker compose run --rm --no-deps laser-prep python selfcheck.py
```

- [ ] **Step 5: Verifikasi tidak ada sisa penyebutan**

```bash
grep -rwiE "mopa|uv|rembg|despeckle" app.py selfcheck.py prep/ templates/ README.md requirements.txt
```

Expected: **tepat satu** baris hasil — komentar pembanding rembg di `prep/raster.py:31`, yang memang sengaja dipertahankan. Bila ada baris lain, betulkan lalu jalankan ulang.

- [ ] **Step 6: Jalankan seluruh cek terakhir kali**

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
```

Expected: `selfcheck ok`

```bash
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add prep/raster.py templates/index.html requirements.txt README.md
git commit -m "docs: buang klaim auto-trim & instruksi rembg, samakan penamaan mode"
```

---

## Cakupan yang sengaja ditinggalkan

Masuk daftar fitur, bukan bagian dari rencana ini: fit-to-box (batas lebar × tinggi), pemrosesan banyak berkas sekaligus, auto-trim margin putih, rotate/mirror. Tetap di luar cakupan sesuai kesepakatan awal project: MarkEzd.dll (mark-ready level 2), input PDF/AI, teks hidup di SVG.
