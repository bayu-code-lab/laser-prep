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

## Dua cabang

| Cabang | Untuk | Input | Output | Yang dikerjakan Python |
|---|---|---|---|---|
| **Logo → Vektor** | Besi / **MOPA** | JPG, PNG, SVG, (DXF/PLT passthrough) | **DXF** (mm) + SVG | Bersihkan bitmap, vektorisasi (vtracer), buang speckle, skala mm presisi |
| **Foto → Grayscale** | Kaca / **UV** | JPG, PNG, TIFF | **PNG grayscale** (DPI benar) | Grayscale, auto-kontras/CLAHE, gamma, crop, skala fisik mm @ DPI |

---

## Instalasi (Windows — komputer dekat mesin laser)

1. Install **Python 3.10+** dari python.org → saat install centang **"Add Python to PATH"**.
2. Ekstrak folder `laser-prep`, buka **Command Prompt** di folder itu, lalu:

   ```bat
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. (Opsional) untuk fitur **hapus background** otomatis, buka `requirements.txt`,
   hapus tanda `#` pada baris `rembg` dan `onnxruntime`, lalu `pip install -r requirements.txt` lagi.

## Menjalankan

```bat
venv\Scripts\activate
python app.py
```

Buka browser ke **http://127.0.0.1:8000** . Selesai — semua jalan lokal, tanpa internet.

> Tip: bikin file `start.bat` berisi dua baris di atas supaya tinggal dobel-klik tiap hari.

---

## Cara pakai

1. Pilih **jenis pekerjaan** (Logo→Vektor untuk MOPA, atau Foto→Grayscale untuk kaca UV).
2. **Seret file** pelanggan ke kotak upload.
3. Isi **Lebar target (mm)** — ukuran fisik hasil ukiran (tinggi mengikuti rasio otomatis).
4. Atur opsi bila perlu (threshold, invert, speckle / DPI, kontras, gamma).
5. Tekan **Proses**, cek **preview sesudah**. Kurang pas? Ubah opsi, proses lagi.
6. **Download** hasilnya (DXF untuk MOPA, PNG untuk UV).

### Import ke EZCAD2

**MOPA (DXF):**
1. EZCAD2 → **File ▸ Import** → pilih file `.dxf`.
2. Ukuran sudah dalam **mm** dan benar; cek di panel posisi/ukuran.
3. Pilih objek → terapkan **Hatch** (isi) sesuai kebutuhan (garis isi untuk marking penuh).
4. Set **pen parameter** (power/speed/frequency) sesuai material (mis. stainless MOPA) — pakai
   pustaka pen yang sudah kamu simpan biar cepat.
5. Mark.

**Kaca UV (PNG):**
1. EZCAD2 → import **bitmap** (PNG grayscale dari alat ini).
2. Set ukuran (mm). Di properti bitmap, aktifkan **grayscale / dithering** bawaan EZCAD2
   sesuai selera (di sinilah EZCAD2 unggul).
3. Set pen parameter untuk UV di kaca. Mark.

---

## Tips kualitas

- **Logo JPG jelek**: naikkan **filter speckle** kalau banyak titik/noise; nyalakan **Invert**
  bila subjek terang di latar gelap; kalau garis putus, matikan threshold otomatis dan geser manual.
- **Kontur ganda** pada garis itu **normal** — vtracer men-trace kedua tepi garis (outline),
  sehingga di EZCAD2 tinggal di-hatch untuk terisi penuh.
- **Foto kaca**: pakai **CLAHE** untuk foto berdetail; **gamma** untuk mengatur terang-gelap
  tengah; DPI 600 cukup untuk kebanyakan pekerjaan (naikkan hanya bila perlu sangat halus).

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
├── prep/
│   ├── __init__.py        # routing ekstensi + ekspor fungsi
│   ├── geometry.py        # SVG→polyline(mm), tulis DXF, render preview
│   ├── vector.py          # cabang MOPA: raster/SVG → DXF + SVG
│   └── raster.py          # cabang UV: foto → PNG grayscale (skala mm @ DPI)
├── templates/index.html   # UI drag-drop + preview
├── samples/               # contoh untuk uji coba
└── _out/                  # hasil (dibuat otomatis)
```
