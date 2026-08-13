# Ukuran & Penempatan — Laser Prep

Tanggal: 2026-08-13
Status: disetujui, siap dibuat rencana implementasi

## Ringkasan

Lima perubahan bertema satu: **apa yang kamu minta harus sama dengan apa yang keluar dari
mesin, dan mendarat di tempat yang benar.**

| # | Isi | Jenis |
|---|---|---|
| a | `size_mm` dihitung sebelum kontur bingkai dibuang — ukuran dilaporkan benar, geometri yang keluar salah | bug |
| b | Geometri DXF berpusat di (0,0) | fitur |
| c | Auto-trim margin polos di mode Grayscale | fitur |
| d | Mirror horizontal, kedua mode | fitur |
| e | Fit-to-box: batas lebar × tinggi | fitur |

Tanpa dependensi baru. Tanpa berkas baru selain penambahan cek di `selfcheck.py`.

**Di luar cakupan, dipisah ke siklus sendiri:** menskalakan DXF/PLT passthrough. `.plt` adalah
HPGL, bukan DXF — `ezdxf` tidak bisa membacanya, jadi itu dua pekerjaan. Dan membaca DXF asing
(ARC, CIRCLE, SPLINE, TEXT, INSERT dengan blok bersarang) adalah subsistem tersendiri yang
gagalnya diam-diam: berkas terbuka, ukurannya salah.

## Masalah

### (a) Ukuran dilaporkan benar, geometri yang keluar salah

Diuji dengan gambar berbingkai persegi penuh — logo hasil scan, screenshot berbingkai, label
produk:

```
diminta        : lebar 40.00 mm
size_mm dilapor: 40.00 x 40.00   <- chip "Ukuran" di UI menampilkan ini
geometri nyata : 16.37 x 16.44 mm <- yang benar-benar ada di DXF
```

`prep/vector.py:174-177` menghitung `size_mm` **sebelum** `_drop_frame_and_speckle` membuang
konturnya. Skala ditetapkan agar *bingkai* selebar 40 mm, lalu bingkainya dibuang — subjeknya
tinggal 16 mm. UI tetap yakin 40 mm.

Operator tidak akan sadar sampai benda keluar dari mesin dengan ukiran kurang dari separuh
ukuran yang diminta.

### (b) Objek mendarat di kuadran, bukan di tengah field

Terverifikasi pada `samples/logo.jpg`, target 40 mm: bbox DXF `0.00 .. 40.00` di kedua sumbu,
pusat geometri di `(20, 20)`. Field EZCAD2 berpusat di origin, jadi setiap import vektor perlu
penengahan manual.

### (c) Margin polos ikut terhitung sebagai ukuran (mode Grayscale)

`process_photo` menskalakan seluruh gambar (`h, w = gray.shape`), termasuk margin kosong. "Lebar
40 mm" bisa berarti 33 mm gambar + 7 mm udara.

Mode Vektor kebal dari ini: `svg_to_polylines_mm` mengambil bbox dari path, bukan dari kanvas.

### (d) Tidak ada cara mencermin

Kaca sering diukir dari sisi belakang; stempel dan cetakan juga perlu tercermin. Sekarang harus
kembali ke editor.

### (e) Tidak ada batas tinggi

Pekerjaan nyata berbunyi "harus muat di 50×30 mm". `svg_to_polylines_mm` sudah menerima dua
target; yang kurang hanya input UI dan wiring.

## Arsitektur

Bug (a), pemusatan (b), dan fit-to-box (e) pada cabang vektor adalah **satu masalah**:
"skalakan dan tempatkan geometri sesuai target". Satu fungsi baru melayani ketiganya, bukan tiga
tambalan terpisah.

Dua fungsi baru di `prep/geometry.py`:

```python
def fit_polylines(
    polylines: List[Polyline],
    target_width_mm: float,
    target_height_mm: float | None = None,
) -> Tuple[List[Polyline], Tuple[float, float]]:
    """Skalakan polyline agar bbox-nya pas target, kembalikan (polyline, ukuran sebenarnya).

    Rasio selalu dijaga. Tanpa target_height_mm: bbox dibuat selebar target_width_mm.
    Dengan target_height_mm: skala = min(lebar_target/lebar_bbox, tinggi_target/tinggi_bbox)
    sehingga hasilnya MUAT di dalam kotak — salah satu sisi pas, sisi lain lebih kecil
    atau sama. Hasil dinormalkan ke pojok (0,0). Bila daftar kosong, kembalikan
    ([], (0.0, 0.0)) — pemanggil sudah menangani kasus 'tidak ada kontur'.
    """

def mirror_polylines(polylines: List[Polyline], width_mm: float) -> List[Polyline]:
    """Cermin horizontal: x -> width_mm - x. Urutan titik dan status tertutup dipertahankan."""
```

### Pemusatan hanya di `write_dxf`

`write_dxf` mengurangi titik-pusat bbox sebelum menulis. Geometri internal tetap dimulai dari
(0,0).

Alasannya: `render_preview` (`prep/geometry.py:125-163`) dan berkas SVG keluaran mengasumsikan
koordinat mulai dari (0,0). Memusatkan di hulu memaksa keduanya ikut berubah tanpa memberi
manfaat apa pun — EZCAD2 satu-satunya yang peduli letak origin, dan ia hanya membaca DXF.

### Urutan baru di `process_photo`

```
hapus background (BGR) -> grayscale -> TRIM -> kontras -> gamma -> bersihkan latar
  -> invert -> MIRROR -> skala
```

Hanya dua langkah yang baru: `TRIM` dan `MIRROR`. Sisanya persis urutan yang ada sekarang —
khususnya `hapus background` yang tetap berjalan pada citra BGR sebelum konversi grayscale, di
tempatnya sekarang.

Trim ditaruh **sebelum** kontras dengan sengaja: auto-kontras menghitung persentil atas seluruh
gambar, sehingga margin kosong yang lebar menggeser hasilnya. Memangkas lebih dulu membuat
kontras dihitung dari gambar yang sebenarnya. Menaruh trim sesudah `hapus background` juga
berarti latar yang baru diputihkan ikut terpangkas.

## Perubahan per berkas

### `prep/geometry.py`

- Tambah `fit_polylines` dan `mirror_polylines` (signature di atas).
- `write_dxf`: hitung bbox dari `polylines`, kurangi titik pusatnya dari setiap titik sebelum
  `add_lwpolyline`. Daftar kosong tetap menghasilkan DXF kosong yang sah, seperti sekarang.

### `prep/vector.py`

- `process_raster_logo` dan `process_svg_input` menerima `target_height_mm: float | None = None`
  dan `mirror: bool = False`.
- `process_raster_logo`: setelah `_drop_frame_and_speckle`, panggil `fit_polylines` pada kontur
  yang **tersisa**; pakai `size_mm` yang dikembalikannya. Ini perbaikan (a).
- `process_svg_input`: teruskan `target_height_mm` ke `svg_to_polylines_mm`. Tidak membuang
  kontur, jadi tidak perlu re-fit.
- Kedua fungsi: bila `mirror`, panggil `mirror_polylines` sebelum `write_dxf` dan
  `render_preview`, sehingga preview menunjukkan apa yang akan diukir.
- Input raster dan input SVG memakai jalur cermin yang sama (polyline), bukan membalik bitmap
  untuk yang satu dan polyline untuk yang lain.

### `prep/raster.py`

- `process_photo` menerima `target_height_mm: float | None = None`, `mirror: bool = False`,
  `autotrim: bool = True`.
- Helper baru:

  ```python
  def _trim_margin(gray: np.ndarray, tol: int = 12) -> Tuple[np.ndarray, bool]:
      """Buang margin polos di keempat sisi. Return (hasil, apakah_terpangkas).

      Latar diambil dari median piksel tepi — bukan diasumsikan putih — sehingga logo
      terang di latar gelap juga terpangkas benar. Bila seluruh gambar seragam
      (tak ada isi), kembalikan gambar apa adanya.
      """
  ```

  Deteksi: `mask = |gray - warna_tepi| > tol`, ambil bbox dari `mask`. Bila `mask` kosong,
  tidak memangkas.
- Penskalaan fisik memakai `scale = min(lebar_target/w, tinggi_target/h)` bila
  `target_height_mm` ada, selain itu `lebar_target/w` seperti sekarang.
- Mirror memakai `cv2.flip(gray, 1)` tepat sebelum penskalaan.

### `app.py`

Tiga parameter Form baru pada `process()`:

- `height_mm: float = Form(0.0)` — `0` berarti tak dipakai, diterjemahkan jadi `None`.
- `mirror: bool = Form(False)` — diteruskan ke kedua cabang.
- `autotrim: bool = Form(True)` — hanya cabang grayscale.

`height_mm` divalidasi seperti `width_mm` yang sudah ada: nilai tak masuk akal jatuh ke default.

### `templates/index.html`

- Kolom "Tinggi maks (mm)" di sebelah "Lebar target (mm)", boleh dikosongkan. Kosong berarti
  perilaku persis seperti sekarang.
- Checkbox "Cermin horizontal" di **kedua** panel opsi.
- Checkbox "Auto-trim margin polos" di panel Grayscale, **tercentang** secara default.
- Form mengirim `height_mm`, `mirror`, dan (khusus grayscale) `autotrim`.

## Peringatan bagi operator

Bila tinggi yang membatasi hasil, tambahkan peringatan:

> Dibatasi tinggi maks — hasil 26.7 × 20 mm, bukan 40 mm lebar.

Tanpa ini operator mengetik 40 lalu bingung kenapa chip menunjukkan 26.7.

Bila auto-trim memangkas, tambahkan peringatan bahwa margin polos dibuang sebelum penskalaan,
sehingga jelas kenapa hasilnya berbeda dari gambar sumber.

## Verifikasi

Lima cek baru di `selfcheck.py`, mengikuti pola yang ada: memanggil `app.process()` langsung,
`assert` polos, tanpa dependensi baru. Setiap cek wajib **terbukti gagal** saat perbaikannya
dibalikkan — sebuah cek yang tidak bisa gagal bukan cek.

| Cek | Membuktikan |
|---|---|
| `check_frame_drop_size` | gambar berbingkai penuh + subjek lebih kecil; diminta 40 mm, bbox DXF benar-benar ≈40 mm, dan `size_mm` yang dilaporkan cocok dengan bbox itu |
| `check_dxf_centered` | pusat bbox DXF ≈ (0,0) |
| `check_fit_box` | minta 40×20 pada gambar persegi; hasil muat di dalam kotak dan rasio terjaga |
| `check_mirror` | mode Grayscale: PNG hasil dengan `mirror=True` sama persis dengan `np.fliplr` dari PNG hasil `mirror=False` — bukan sekadar "berbeda", yang akan lolos untuk perubahan apa pun |
| `check_autotrim` | gambar dengan margin polos lebar; lebar piksel hasil sesuai artwork, bukan kanvas |

Cek yang sudah ada — `check_invert_grayscale`, `check_preview_thumb`,
`check_svg_preview_before` — harus tetap lulus.

Perintah (cv2 tidak terpasang di host):

```bash
docker compose run --rm --no-deps laser-prep python selfcheck.py
docker compose run --rm --no-deps laser-prep python -m prep.vector
```

Verifikasi manual: proses `samples/logo.jpg` dan `samples/photo.png` lewat UI di kedua mode,
dengan dan tanpa tinggi maks, dengan dan tanpa mirror; preview menunjukkan apa yang akan diukir.

## Di luar cakupan

Menskalakan DXF/PLT passthrough (siklus sendiri, lihat Ringkasan). Mirror vertikal — sama dengan
putar 180° lalu cermin horizontal, dan hampir tak pernah dipakai; tambahkan bila ternyata perlu.
Pemrosesan banyak berkas sekaligus, rotate, dan preset tersimpan tetap di daftar fitur. Tetap di
luar cakupan sesuai kesepakatan awal project: MarkEzd.dll (mark-ready level 2), input PDF/AI,
teks hidup di SVG.
