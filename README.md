# 🔧 Laser Prep

Alat **internal operator** untuk mengubah file mentah pelanggan menjadi file
**siap-import EZCAD2** — supaya kamu tidak buang waktu benerin file sebelum mengukir.

Jalan sebagai **web app lokal** di komputermu (bukan hosting), drag-drop, dengan
**preview sebelum/sesudah** sehingga kamu bisa cek hasilnya sebelum dipakai.

---

## ⚠️ Batasan yang harus kamu pahami dulu (penting)

Alat ini menghasilkan file **import-ready**, BUKAN **mark-ready**. Artinya:

- Kamu **tetap** membuka EZCAD2, meng-import file, lalu **set parameter sendiri**
  (power / speed / frequency / hatch / fill). Parameter itu tinggal di dalam file
  `.ezd` milik EZCAD2 dan **tidak bisa** ditulis dari Python — format `.ezd`
  proprietary. Jadi ini memang sesuai kesepakatan: Python siapkan geometrinya,
  parameter kamu atur di EZCAD2.
- **Dithering / halftone / grayscale bitmap** sengaja **tidak** dikerjakan di sini —
  EZCAD2 lebih unggul untuk itu. Python hanya menyiapkan grayscale bersih + ukuran benar.
- Realistis, sekitar **60–70%** file pelanggan bisa lolos otomatis dengan rapi.
  Sisanya (logo sangat berantakan / resolusi rendah) tetap perlu sentuhan manual.
  Itu normal — targetnya menghemat mayoritas waktumu, bukan 100% tanpa sentuh.

---

## Dua mode

| Mode | Untuk | Input | Output | Yang dikerjakan Python |
|---|---|---|---|---|
| **Ke Vektor (DXF)** | Ukiran garis / kontur | JPG, PNG, SVG, (DXF/PLT passthrough) | **DXF** (mm) + SVG | Bersihkan bitmap, vektorisasi (vtracer), buang speckle, skala mm presisi |
| **Ke Grayscale (PNG)** | Ukiran bernada abu-abu | JPG, PNG, TIFF | **PNG grayscale** (DPI benar) | Grayscale, auto-trim, auto-kontras/CLAHE, gamma, skala fisik mm @ DPI |

> DXF/PLT masuk sebagai **passthrough** (bukan divektorisasi ulang) — lihat bagian
> **DXF/PLT: ukuran dilaporkan, bukan diubah diam-diam** di bawah untuk detail perilaku
> dan batasannya.

---

## Instalasi (Windows — komputer dekat mesin laser)

1. Install **Python 3.10+** dari python.org → saat install centang **"Add Python to PATH"**.
2. Ekstrak folder `laser-prep`, buka **Command Prompt** di folder itu, lalu:

   ```bat
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Menjalankan

```bat
venv\Scripts\activate
python app.py
```

Buka browser ke **http://127.0.0.1:8000** . Selesai — semua jalan lokal, tanpa internet.

> Tip: bikin file `start.bat` berisi dua baris di atas supaya tinggal dobel-klik tiap hari.

---

## Cara pakai

1. Pilih **mode** (Ke Vektor (DXF), atau Ke Grayscale (PNG)).
2. **Seret file** pelanggan ke kotak upload — satu berkas, atau beberapa sekaligus untuk
   diproses sebagai **batch** (lihat bagian **Batch** di bawah).
3. Isi **Lebar target (mm)** — ukuran fisik hasil ukiran. Isi **Tinggi maks (mm)** bila
   hasilnya harus muat di area tertentu; kosongkan bila tinggi boleh ikut rasio.
4. Atur opsi bila perlu (threshold, invert, cermin, **putar 0°/90°/180°/270°**, speckle /
   DPI, kontras, gamma, auto-trim, **lensa** area kerja untuk cek muat). Kalau setelan ini
   sering dipakai ulang, simpan sebagai **preset** (lihat bagian **Preset** di bawah).
5. Tekan **Proses**, cek **preview sesudah** — termasuk kotak area kerja lensa yang
   menunjukkan muat atau tidaknya hasil. Kurang pas? Ubah opsi, proses lagi.
6. **Download** hasilnya (DXF untuk mode Vektor, PNG untuk mode Grayscale). Kalau
   memproses batch dan hasil suksesnya lebih dari satu, ada tombol **"⬇ Unduh semua
   (ZIP)"** untuk mengambil semuanya sekaligus.

### Import ke EZCAD2

**Import DXF:**
1. EZCAD2 → **File ▸ Import** → pilih file `.dxf`.
2. Ukuran sudah dalam **mm** dan benar; cek di panel posisi/ukuran.
3. Pilih objek → terapkan **Hatch** (isi) sesuai kebutuhan (garis isi untuk marking penuh).
4. Set **pen parameter** (power/speed/frequency) sesuai material (mis. stainless) — pakai
   pustaka pen yang sudah kamu simpan biar cepat.
5. Mark.

**Import PNG grayscale:**
1. EZCAD2 → import **bitmap** (PNG grayscale dari alat ini).
2. Set ukuran (mm). Di properti bitmap, aktifkan **grayscale / dithering** bawaan EZCAD2
   sesuai selera (di sinilah EZCAD2 unggul).
3. Set pen parameter sesuai material kaca. Mark.

---

## Batch (banyak berkas sekaligus)

Kamu bisa **seret beberapa berkas sekaligus** ke kotak upload (atau pilih banyak lewat
dialog file browser). Cocok untuk hari-hari banyak orderan yang mode dan setelannya sama.

- **Satu set setelan berlaku untuk seluruh batch** — tidak ada setelan per berkas.
  Kelompokkan dulu berkas yang memang butuh threshold/lensa/dll. yang sama sebelum
  memprosesnya bareng; yang beda setelan, proses sebagai batch terpisah.
- Berkas diproses **berurutan** dengan progres di layar, mis. "Memproses 5 dari 12…".
- Tiap berkas mendapat **satu baris hasil**. Berkas yang gagal tampil sebagai **baris
  merah** berisi pesan errornya, dan batch **tetap lanjut** ke berkas berikutnya — satu
  berkas rusak tidak menggagalkan sisanya.
- Kalau hasil suksesnya lebih dari satu, muncul tombol **"⬇ Unduh semua (ZIP)"**.
- Ruang hasil satu sesi batch dibatasi **200 MB**. Kalau penuh, berkas berikutnya ditolak
  dengan pesan yang jelas di layar — **unduh dulu hasil yang sudah ada** (satu-satu atau
  lewat ZIP), lalu proses sisanya sebagai batch baru.

## Preset (setelan tersimpan)

Setelan yang sering dipakai ulang bisa **disimpan dengan nama** lalu dimuat lagi kapan
saja lewat dropdown **Preset** di atas panel setelan. Preset merekam **seluruh setelan**,
termasuk **mode**-nya (Ke Vektor atau Ke Grayscale) — jadi satu klik langsung
mengembalikan kondisi lengkap, tidak perlu ganti mode dan isi ulang opsi satu-satu.

- **Simpan** memberi nama pada setelan saat ini; **Hapus** membuang preset yang sedang
  dipilih.
- Preset tersimpan di **browser kamu** (`localStorage`), **bukan di server laser-prep**.
  Konsekuensinya:
  - preset yang dibuat di Chrome **tidak muncul** di Firefox/Edge, dan preset di komputer
    ini **tidak ikut** kalau alat ini dibuka dari komputer lain — preset itu per-browser,
    per-mesin;
  - kalau kamu **bersihkan data situs / cache / cookies browser** ini, semua preset ikut
    **hilang**. Tidak ada cadangan otomatis di server, jadi catat setelan penting di
    tempat lain kalau memang krusial.

## Area kerja & cek "muat tidak" (lensa)

Panel **preview sesudah** menggambar **kotak garis putus-putus** yang mewakili area
kerja lensa laser yang sedang dipilih, dengan hasil ukiran digambar **di dalamnya pada
skala sebenarnya** — jadi pertanyaan "muat tidak di lensa ini" terjawab di layar,
sebelum berkasnya masuk EZCAD2/mesin.

- Daftar **lensa** ada di panel setelan dan bisa **ditambah/dihapus** sendiri (mis. kalau
  toko punya lensa lain, ketik nama dan ukurannya). Isi awalnya:
  - **F110** — 70 × 70 mm
  - **F163** — 110 × 110 mm
- Hasil yang **melebihi** kotak lensa membuat kotaknya berubah jadi **garis merah**
  disertai peringatan di layar — tapi ini **cuma peringatan, tidak pernah memblokir**
  proses atau unduhan. Keputusan akhir "boleh mark atau tidak" tetap di tanganmu.
- Tombol dua-keadaan **"pas layar" / "skala area kerja"** di pojok preview dipakai untuk
  gonta-ganti tampilan:
  - **"pas layar"** membesarkan hasil supaya penuh di panel — enak untuk cek detail garis.
  - **"skala area kerja"** menampilkan proporsi asli terhadap kotak lensa — penting
    supaya, misalnya, logo 5 mm di dalam lensa F163 (110 mm) tidak cuma terlihat sebagai
    titik yang mutunya tak bisa dinilai dari layar.

## Rotasi (0° / 90° / 180° / 270°)

Tersedia di **kedua mode** (Ke Vektor dan Ke Grayscale), searah **jarum jam** sebagaimana
terlihat di layar. Rotasi diterapkan **sebelum penskalaan** (dan sebelum cermin) — jadi
kalau kamu isi **Lebar target 40 mm**, itu selalu lebar hasil akhir **setelah** diputar,
bukan lebar berkas sebelum diputar. Aman diganti-ganti sambil lihat preview sesudah untuk
cari orientasi yang pas.

Rotasi (dan cermin) **tidak** diterapkan pada berkas DXF/PLT yang lewat sebagai
passthrough — lihat bagian berikutnya.

## DXF/PLT: ukuran dilaporkan, bukan diubah diam-diam

Kalau kamu masukkan **DXF atau PLT** ke mode Ke Vektor, alat ini memperlakukannya sebagai
**passthrough**: ukuran asli berkas **dilaporkan** di baris hasil, dan secara bawaan
**tidak** diskalakan — berkas yang ukurannya sudah benar tidak dirusak alat ini.

- Mau tetap diskalakan ke **Lebar target (mm)**? Tekan tombol **"Skalakan ke ukuran
  target"** yang muncul di baris hasil berkas itu. **PLT yang diskalakan keluar sebagai
  DXF** (bukan PLT lagi).
- DXF **tanpa keterangan satuan** di headernya dilaporkan sebagai **mm** disertai
  **peringatan** di layar — cek manual kalau berkasnya berasal dari software yang biasa
  memakai satuan lain (inch, dsb.), karena alat ini menebak, bukan memastikan.
- DXF **tidak punya pratinjau gambar** di panel sebelum/sesudah — yang tampil hanya
  **jejak kotaknya (bounding box)** di dalam kotak area kerja/lensa, supaya kamu tetap
  bisa cek muat atau tidak walau tidak lihat bentuk aslinya.
- **Cermin dan rotasi tidak diterapkan** pada berkas passthrough ini — kalau kamu
  menyalakan opsi itu untuk berkas DXF/PLT yang tidak diskalakan, alat memberi
  **peringatan** di layar alih-alih diam-diam mengabaikannya.

---

## Tips kualitas

- **Logo JPG jelek**: naikkan **filter speckle** kalau banyak titik/noise; nyalakan **Invert**
  bila subjek terang di latar gelap; kalau garis putus, matikan threshold otomatis dan geser manual.
- **Kontur ganda** pada garis itu **normal** — vtracer men-trace kedua tepi garis (outline),
  sehingga di EZCAD2 tinggal di-hatch untuk terisi penuh.
- **Foto kaca**: pakai **CLAHE** untuk foto berdetail; **gamma** untuk mengatur terang-gelap
  tengah; DPI 600 cukup untuk kebanyakan pekerjaan (naikkan hanya bila perlu sangat halus).
- **Cermin horizontal**: untuk stempel, cetakan, dan kaca yang diukir dari sisi belakang
  supaya terbaca benar dari depan. Pada mode Vektor, berkas SVG yang diunduh tidak ikut
  dicermin — pakai DXF-nya.
- **Auto-trim** membuang tepi polos sebelum penskalaan, jadi ukuran mm mengacu ke gambarnya
  dan bukan ke kanvas. Matikan bila bingkai kosongnya memang ingin ikut terukir.

## Belum didukung (bisa jadi pengembangan lanjutan)

- **Teks hidup** di dalam SVG (font). Untuk sekarang, outline/convert-to-curves dulu di
  editor (Illustrator/Inkscape) sebelum masuk. Vektorisasi dari raster tidak terpengaruh ini.
- **PDF / AI** langsung. Ekspor dulu ke SVG atau PNG.
- **Level 2 (mark-ready via SDK `MarkEzd.dll`)** — menyuntik artwork ke template `.ezd`
  ber-parameter agar benar-benar "tekan start". Sengaja belum dibuat sesuai kesepakatan.

---

## Struktur project

```
laser-prep/
├── app.py                 # web app lokal (FastAPI)
├── requirements.txt
├── README.md
├── selfcheck.py           # cek end-to-end: docker compose run --rm --no-deps laser-prep python selfcheck.py
├── prep/
│   ├── __init__.py        # routing ekstensi + ekspor fungsi
│   ├── geometry.py        # SVG→polyline(mm), tulis DXF, render preview
│   ├── vector.py          # mode Ke Vektor: raster/SVG → DXF + SVG
│   ├── raster.py          # mode Ke Grayscale: foto → PNG grayscale (skala mm @ DPI)
│   └── passthrough.py     # DXF/PLT passthrough: baca ukuran, skala opsional ke DXF
├── templates/index.html   # UI drag-drop + preview
├── samples/               # contoh untuk uji coba
└── _out/                  # hasil (dibuat otomatis)
```
