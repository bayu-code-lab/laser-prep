# Perbaikan Bug & Penamaan Berbasis Format — Laser Prep

Tanggal: 2026-08-12
Status: disetujui, siap dibuat rencana implementasi

## Ringkasan

Satu pass perbaikan pada Laser Prep. Dua bagian:

- **A. Penamaan** — dua cabang alat dinamai berdasarkan **format output** (`Ke Vektor (DXF)`,
  `Ke Grayscale (PNG)`), bukan berdasarkan jenis mesin (MOPA/UV).
- **B. Enam perbaikan bug & dokumentasi** yang sudah terverifikasi ada di kode saat ini.

Tanpa dependensi baru dan tanpa fitur baru. Satu berkas baru: `selfcheck.py` (lihat
bagian Verifikasi).

## Masalah

### Penamaan mengikat alat ke dua mesin

Label sekarang mencampur mesin (MOPA/UV) dengan material (besi/kaca) untuk membedakan dua hal
yang sebenarnya berbeda di **format output**. Akibatnya:

- Alat terlihat hanya cocok untuk dua mesin itu. Padahal cabang DXF berguna untuk mesin apa pun
  yang menerima DXF (CO2, fiber, plotter).
- Operator baru tahu "saya butuh DXF", belum tentu tahu apa itu MOPA.

### Enam cacat terverifikasi

| # | Cacat | Lokasi |
|---|---|---|
| 1 | Checkbox "Balik (negatif)" pada cabang grayscale tidak berefek apa pun | `app.py:157` tidak meneruskan `invert` ke `process_photo` |
| 2 | Preview "sesudah" menyajikan PNG hasil penuh (bisa >12000 px) ke `<img>` | `prep/raster.py:144` |
| 3 | Docstring mengklaim fitur `crop/auto-trim` yang tidak ada kodenya | `prep/raster.py:4`, `README.md:33` |
| 4 | UI & README menyuruh install `rembg` yang sudah dihapus dari `requirements.txt` | `templates/index.html:117-118`, `README.md:47-49` |
| 5 | Parameter `despeckle` diterima lalu tidak pernah dipakai | `prep/vector.py:37,147,159` |
| 6 | Panel "sebelum" untuk input SVG menampilkan gambar hasil, bukan sumber | `prep/vector.py:220` |

## Bagian A — Penamaan berbasis format

`EZCAD2` tetap disebut: itu software tujuan import, bukan jenis mesin. Contoh material
(stainless, kaca) tetap ada di bagian README tentang *set pen parameter* — di situ memang
relevan sebagai instruksi operator, bukan sebagai nama fitur.

| Hal | Sekarang | Menjadi |
|---|---|---|
| Label tombol | `Logo → Vektor (besi / MOPA)` | `Ke Vektor (DXF)` |
| Label tombol | `Foto → Grayscale (kaca / UV)` | `Ke Grayscale (PNG)` |
| Nilai `job` di API | `"mopa"` / `"uv"` | `"vector"` / `"grayscale"` |
| id elemen HTML | `opts-mopa`, `opts-uv`, `invert_uv` | `opts-vector`, `opts-grayscale`, `invert_gray` |
| Nama file output | `{stem}_uv.png` | `{stem}_grayscale.png` |
| Chip "Mode" pada hasil | `Vektor / MOPA`, `Grayscale / UV` | `Vektor (DXF)`, `Grayscale (PNG)` |
| Teks hint di bawah tombol | menyebut besi/MOPA, kaca/UV | menyebut apa yang dihasilkan (lihat di bawah) |
| Teks `dropinfo` | `MOPA: … · UV: …` | `Vektor: JPG, PNG, SVG, DXF · Grayscale: JPG, PNG, TIFF` |

Teks hint baru di bawah pemilih jenis pekerjaan:

> **Ke Vektor (DXF)**: ubah logo/gambar jadi garis kontur (DXF + SVG), ukuran mm tepat.
> **Ke Grayscale (PNG)**: ubah foto jadi PNG abu-abu, ukuran fisik mm pada DPI yang benar.

Pesan error diganti:

- `"Format {ext} tak didukung untuk cabang MOPA."`
  → `"Format {ext} tak didukung untuk mode Vektor."`
- `"Cabang Kaca UV butuh gambar raster (JPG/PNG/...). Dapat: {ext}"`
  → `"Mode Grayscale butuh gambar raster (JPG/PNG/TIFF). Dapat: {ext}"`

Docstring modul yang menyebut MOPA/UV diganti menjadi menyebut format:
`app.py:5-6`, `prep/vector.py:2`, `prep/raster.py:2`.

README yang ikut berubah:

- Tabel "Dua cabang" (baris 30–33): kolom **Untuk** yang sekarang berisi `Besi / MOPA` dan
  `Kaca / UV` diganti menjadi `Ukiran garis / kontur` dan `Ukiran bernada abu-abu`.
- Langkah pemakaian (baris 66, 71): sebut nama mode baru, bukan nama mesin.
- Judul bagian import (baris 75, 83): `**MOPA (DXF):**` → `**Import DXF:**`,
  `**Kaca UV (PNG):**` → `**Import PNG grayscale:**`. Isi langkahnya tidak berubah, termasuk
  contoh material pada langkah *set pen parameter*.
- Komentar pada pohon struktur project (baris 120–121): sebut format, bukan mesin.

Komentar di `requirements.txt:11` (`# Hapus background di UV kini pakai flood-fill warna…`)
diganti menjadi menyebut mode grayscale, bukan UV.

Nilai `job` diganti tanpa alias lama. Tidak ada konsumen API selain `templates/index.html`,
sehingga tidak ada yang rusak, dan menyisakan nama internal yang salah hanya menambah beban.

## Bagian B — Enam perbaikan

**1. Invert grayscale mati.** Teruskan `invert=invert` pada pemanggilan `process_photo` di
`app.py:157`. Parameter `invert` sudah ada di signature `process()` maupun di `process_photo`;
hanya penerusannya yang hilang.

**2. Preview "sesudah" kegedean.** Tambah helper di `prep/raster.py`:

```python
def _thumb(img, path, max_px=900):
    """Simpan thumbnail JPEG — preview cukup segini, file penuh hanya untuk download."""
```

Dipakai untuk dua hal: preview `before` (menggantikan blok inline yang sekarang ada di
`raster.py:81-85`) dan preview `after` (menggantikan `preview_after=png_path`). PNG hasil
resolusi penuh tetap ditulis ke `png_path` dan tetap jadi satu-satunya isi tautan download.

**3. Docstring bohong.** Hapus frasa `crop/auto-trim` dari docstring `prep/raster.py:4` dan kata
`crop` dari tabel README baris 33. Auto-trim belum ada; kalau nanti dibuat, docstring menyusul.

**4. rembg.** Ganti label dan hint checkbox di `templates/index.html:117-118` menjadi:

> Hapus background polos
> Latar seragam yang menyambung dari tepi dijadikan putih. Teks tetap aman. Untuk foto berlatar
> ramai efeknya minim.

Hapus langkah instalasi opsional rembg di `README.md:47-49`. Komentar pembanding di
`prep/raster.py:31` **tetap** — komentar itu menjelaskan alasan memilih flood-fill ketimbang
rembg, dan alasan itu masih berlaku.

**5. `despeckle` mati.** Hapus parameter dari signature `_preprocess_bitmap`
(`prep/vector.py:37`) dan `process_raster_logo` (`prep/vector.py:147`), serta dari pemanggilan di
`prep/vector.py:159`. Tidak ada pemanggil yang mengirimnya; pembuangan speckle sudah ditangani
`filter_speckle` milik vtracer.

**6. Preview "sebelum" SVG.** Ubah `preview_before=prev_after` menjadi `preview_before=src_path`
di `prep/vector.py:220`. File SVG sumber sudah berada di folder sesi dan bisa ditampilkan
langsung oleh browser di `<img>`, jadi tidak perlu render tambahan.

## Verifikasi

Bug #1 hidup di **wiring `app.py`**, bukan di `prep/`. `process_photo` sendiri sudah menghormati
`invert` hari ini, sehingga self-check di level `prep/raster.py` akan lulus meski bug-nya ada —
cek yang tidak bisa gagal bukan cek. Karena itu verifikasi harus menembus endpoint.

Buat berkas baru `selfcheck.py` di akar project: memanggil fungsi `app.process()` **langsung**
lewat `asyncio.run` dengan `UploadFile` dari `BytesIO`. Tanpa server, tanpa `httpx`, tanpa
pytest — **nol dependensi baru**, mengikuti gaya assert polos `prep/vector.py:227-238`. Cek yang
sama sekaligus membuktikan penggantian nilai `job` di Bagian A tidak merusak wiring.

Isi self-check:

1. **Invert grayscale** (bug #1) — proses gambar sintetis dua kali, `invert=False` lalu `True`;
   `assert` rata-rata piksel PNG hasil berbalik dari gelap ke terang.
2. **Ukuran preview** (bug #2) — `assert` sisi terpanjang berkas `before` dan `after` ≤ 900 px,
   sementara PNG di tautan download tetap resolusi penuh.
3. **Preview sebelum untuk SVG** (bug #6) — `assert` `before` menunjuk ke berkas `.svg` sumber
   dan berbeda dari `after`.

Self-check `prep/vector.py` yang sudah ada harus tetap lulus setelah parameter `despeckle`
dihapus (membuktikan tidak ada `TypeError` dari pemanggil).

Perintah (cv2 tidak terpasang di host; project ini berjalan di Docker):

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Verifikasi manual setelah implementasi:

- `grep -rwiE "mopa|uv|rembg|despeckle" app.py selfcheck.py prep/ templates/ README.md requirements.txt`
  tidak menghasilkan apa pun kecuali komentar pembanding rembg di `prep/raster.py:31` yang
  memang dipertahankan. (`-w` menjaga `uvicorn` tidak ikut terjaring.)
- Kedua cabang diproses lewat UI memakai berkas di `samples/`, preview sebelum dan sesudah
  keduanya tampil, tautan download berfungsi.

## Di luar cakupan

Masuk daftar fitur, bukan bagian dari pass ini: fit-to-box (batas lebar × tinggi), pemrosesan
banyak berkas sekaligus, auto-trim margin putih, rotate/mirror. Tetap di luar cakupan sesuai
kesepakatan awal project: MarkEzd.dll (mark-ready level 2), input PDF/AI, teks hidup di SVG.
