# Desain: batch, preset, area kerja, putar, dan DXF/PLT

Tanggal: 2026-08-13
Status: disetujui untuk perencanaan

## Masalah

Lima kekurangan yang muncul dari pemakaian harian, digabung jadi satu paket atas
permintaan operator (keberatan soal ukuran paket sudah diangkat dan diputuskan):

1. **Satu file per proses.** Pesanan 20 gantungan kunci berarti 20 kali unggah,
   isi lebar, klik, unduh.
2. **Setelan diketik ulang tiap job.** Lebar, DPI, gamma yang sama diketik
   berulang kali setiap hari.
3. **DXF/PLT lewat tanpa diperiksa.** File vektor pelanggan disalin apa adanya
   dan alat *tidak memberitahu ukurannya* — operator baru tahu setelah file
   masuk EZCAD2.
4. **Tidak ada rujukan area kerja.** "Muat di lensa atau tidak" baru ketahuan di
   mesin.
5. **Tidak bisa memutar.** Artwork potret di benda lanskap harus diputar di luar
   alat.

## Keputusan yang mengikat

Diputuskan operator selama brainstorming; implementasi tidak boleh menyimpang
tanpa ruling tertulis:

- **Satu set setelan berlaku untuk seluruh batch.** Tidak ada setelan per file.
- **Lensa yang dipakai: F110 (70 × 70 mm) dan F163 (110 × 110 mm)** sebagai isi
  awal daftar; daftar bisa ditambah/dihapus operator lewat UI.
- **DXF/PLT: lapor ukuran, jangan skalakan otomatis.** Penskalaan hanya terjadi
  saat operator menekan tombolnya. File yang sudah benar ukurannya tidak boleh
  dirusak alat.
- **Batch dikerjakan browser dengan permintaan berurutan**, bukan endpoint
  multi-file (alasan di bawah).

## Kenapa batch dijalankan berurutan dari browser

Alternatifnya `file: List[UploadFile]` dalam satu permintaan. Ditolak karena
tiga hal yang terukur, bukan selera:

- **Progres.** Berurutan memberi "5 dari 12" gratis. Multi-file membuat layar
  diam sampai seluruh batch selesai — untuk 12 foto 600 dpi bisa satu menit
  tanpa umpan balik.
- **Isolasi kegagalan.** Satu file rusak jadi satu baris merah; batch lanjut.
  Dalam gelung server, satu pengecualian merusak seluruh balasan.
- **Anggaran tmpfs.** `_out` adalah tmpfs 256 MB. Berurutan memungkinkan server
  memeriksa sisa ruang *sebelum tiap file* dan berhenti dengan angka yang jujur.
  Multi-file sudah terlanjur menerima semuanya sebelum ada yang bisa diperiksa.

Ongkosnya N permintaan HTTP di localhost — tidak terasa.

## Arsitektur

### 1. Batch dan ZIP

**`app.py` — parameter baru pada `POST /process`:**

```
reset: bool = Form(True)            # True = kosongkan folder sesi dulu
rotate: int = Form(0)               # 0 | 90 | 180 | 270
scale_passthrough: bool = Form(False)
```

`reset=True` memanggil `_fresh_session_dir(sid)` seperti sekarang. `reset=False`
memakai folder yang ada (`os.makedirs(..., exist_ok=True)`). Browser mengirim
`reset=true` hanya untuk file pertama batch. Satu boolean — bukan id batch,
bukan mesin status.

`rotate` di luar {0, 90, 180, 270} dinormalkan ke 0.

**Anggaran ruang.** Konstanta `BATCH_BUDGET = 200 * 1024 * 1024`. Sebelum
menulis file yang diunggah, server menjumlah ukuran isi folder sesi. Bila sudah
≥ `BATCH_BUDGET`, file itu **tidak** diproses dan server membalas HTTP 200
dengan:

```json
{"ok": false, "error": "Ruang hasil penuh (200 MB). File ini tidak diproses — unduh hasil yang sudah ada, lalu proses sisanya sebagai batch baru."}
```

Status 200, bukan 500: ini kondisi yang diharapkan, bukan kesalahan server, dan
gelung batch di browser merendernya sebagai baris merah lewat jalur yang sama
dengan galat lain.

**Endpoint baru `POST /zip`.** Badan permintaan JSON `{"names": [...]}`. Untuk
tiap nama:

- wajib cocok `^[A-Za-z0-9_.-]+$` (tanpa pemisah path, tanpa `..`);
- wajib ada sebagai berkas biasa di folder sesi pemanggil.

Nama yang tidak lolos → HTTP 400, tidak ada arsip yang dibuat. Arsip ditulis ke
`tempfile.NamedTemporaryFile(delete=False)` **di luar `_out`** — menulisnya di
dalam tmpfs berarti mengemas 180 MB hasil menjebol tmpfs-nya sendiri. Dibalas
sebagai `FileResponse` dengan nama unduhan `laser-prep-<sid[:6]>.zip` dan
`BackgroundTask(os.remove, path)` untuk membersihkan temp file setelah terkirim.

Daftar nama datang dari browser, bukan hasil tebakan server atas isi folder.
Menebak berarti menyaring dengan pola nama (`_before.jpg`, `_after.png`), dan
pola itu rusak diam-diam begitu ada berkas baru bernama mirip. Browser sudah
memegang daftar pastinya dari balasan-balasan sebelumnya.

**`templates/index.html`.** `<input type="file" multiple>`; drop zone menerima
banyak berkas; `picked` jadi array. Tombol Proses mengulang berurutan dengan
`await`, mengirim `reset = (i === 0)`, dan menampilkan "Memproses 5 dari 12…".
File gagal → baris merah, gelung lanjut.

Panel hasil jadi **satu baris per file**, masing-masing berisi pratinjau
sebelum/sesudah, chip ukuran, tautan unduh, dan peringatannya sendiri. Satu file
tampil persis seperti sekarang — bukan cabang kode terpisah, hanya daftar
berisi satu elemen. Tombol "⬇ Unduh semua (ZIP)" muncul saat hasil sukses > 1.

Tabrakan nama sudah aman lewat `_safe_stem` yang menempelkan 6 hex acak.

### 2. Preset dan daftar lensa (localStorage)

Tidak ada penyimpanan di server.

```
lp_presets  = { "<nama>": { job, width_mm, height_mm, rotate, mirror,
                            auto_threshold, threshold, invert, filter_speckle,
                            dpi, gamma, autocontrast, clahe, autotrim, remove_bg } }
lp_fields   = [ {"nama":"F110","w":70,"h":70}, {"nama":"F163","w":110,"h":110} ]
lp_field_sel= "<nama lensa terpilih terakhir>"
```

`lp_fields` diisi dengan dua lensa di atas bila kuncinya belum ada.

UI preset: satu baris di atas panel kontrol — `<select>` + tombol Simpan +
Hapus. Simpan menanyakan nama lewat `prompt()`; nama yang sudah ada ditimpa
setelah konfirmasi. Memuat preset menulis **seluruh** kontrol termasuk mode,
lalu memicu peralihan panel mode.

**Perapian yang menyertai.** Kode submit sekarang membangun `FormData` dengan
menulis tiap `$("#…")` satu per satu. Preset perlu membaca *dan menulis*
kumpulan nilai yang sama. Keduanya memakai satu pasang fungsi
`bacaSetelan()` / `tulisSetelan(obj)`, dan submit ikut memakai `bacaSetelan()`.
Tanpa penyatuan ini ada dua daftar nama kontrol yang harus selalu sinkron, dan
salah satunya pasti ketinggalan saat kontrol baru ditambahkan.

### 3. Kotak area kerja di pratinjau

Panel "Sesudah" tiap baris menggambar persegi garis putus-putus berbanding
`w:h` lensa terpilih, dengan hasil di dalamnya **pada skala sebenarnya**:
lebar hasil `size_mm[0] / field_w × 100%`, tinggi `size_mm[1] / field_h × 100%`,
dipusatkan. Murni DOM/CSS — ukuran mm sudah ada di balasan.

Hasil melebihi field → garis merah + peringatan yang menyebut nama dan ukuran
lensa. **Memperingatkan, tidak pernah memblokir.**

Tombol dua-keadaan di panel itu: **"pas layar"** / **"skala area kerja"**.
Alasannya: logo 5 mm di dalam field 110 mm jadi titik yang tak bisa dinilai
mutunya, jadi operator harus bisa kembali ke tampilan penuh.

### 4. Putar

Dropdown 0 / 90 / 180 / 270, berlaku di kedua mode.

**Arah: searah jarum jam sebagaimana terlihat di layar, sama di kedua mode.**
Ini wajib dipatok oleh pengujian, bukan diserahkan ke tanda plus-minus yang
kebetulan.

**Urutan transformasi wajib sama di kedua mode: putar dulu, baru cermin.**
Untuk 90° dan 270°, cermin-lalu-putar tidak sama dengan putar-lalu-cermin, jadi
urutan yang berbeda antar mode akan menghasilkan dua jawaban berbeda untuk
setelan yang sama.

- **Grayscale** (`prep/raster.py`): urutan jadi
  `… → invert → PUTAR → cermin → skala`. `cv2.rotate` dengan konstanta
  `ROTATE_90_CLOCKWISE` / `ROTATE_180` / `ROTATE_90_COUNTERCLOCKWISE`.
  Penskalaan membaca `h, w = gray.shape` sesudahnya, jadi otomatis memakai
  dimensi hasil putaran.
- **Vektor** (`prep/geometry.py` + `prep/vector.py`): fungsi baru
  `rotate_polylines(polylines, deg)` dipanggil **sebelum** `fit_polylines`.
  Urutan efektifnya jadi putar → fit → cermin, yang sama dengan grayscale
  (cermin tetap sesudah fit karena `mirror_polylines` butuh lebar akhir).

Putar sebelum penskalaan berarti "lebar target 40 mm" selalu merujuk lebar hasil
akhir, bukan lebar sebelum diputar.

### 5. DXF/PLT — modul baru `prep/passthrough.py`

**`read_size(path) -> (w_mm, h_mm, warnings)`**

- `.dxf`: `ezdxf.readfile` + `ezdxf.bbox.extents(msp)`. Satuan dibaca dari
  `$INSUNITS`: 4 = mm (apa adanya), 1 = inci (× 25.4), 0 = tanpa satuan →
  angka dilaporkan sebagai mm **disertai peringatan eksplisit** bahwa file
  tidak menyatakan satuannya. Satuan lain yang dikenal ezdxf dikonversi lewat
  faktornya; yang tidak dikenal diperlakukan seperti 0.
- `.plt`: pengurai HPGL sendiri. Perintah `PU`/`PD`/`PA` dengan pasangan
  koordinat, `1 satuan = 0.025 mm` (40 satuan/mm). `IN`, `SP`, `LT`, `VS`, `PW`
  diabaikan. `PD` membentuk polyline; `PU` mengakhiri polyline berjalan.
  **`PR` (koordinat relatif) tidak didukung** — bila ditemui, alat berhenti
  dengan galat yang menyebutnya, bukan melaporkan angka yang salah.
- File tanpa geometri yang bisa dibaca → galat, bukan ukuran 0 × 0.

**Balasan passthrough** kini memuat `size_mm` (sebelumnya `null`), sehingga chip
ukuran dan kotak area kerja bekerja untuk DXF/PLT juga.

**Penskalaan** hanya saat `scale_passthrough=true` (tombol "Skalakan ke ukuran
target" pada baris hasil itu, memanggil `/process` ulang untuk file tersebut):

- `.dxf` → DXF baru lewat `ezdxf.transform.scale_uniform` lalu `translate`
  agar terpusat di (0,0), konsisten dengan keluaran vektor lainnya. Busur,
  spline, dan blok **tidak diratakan** jadi garis patah. `rotate` diterapkan
  lewat `ezdxf.transform.z_rotate`.
- `.plt` → **keluar sebagai DXF**, bukan PLT. Setelah PLT terurai jadi polyline,
  `rotate_polylines` + `fit_polylines` + `write_dxf` yang sudah ada dan sudah
  teruji langsung terpakai, termasuk pemusatan di (0,0). Menulis HPGL kembali
  berarti kode baru tanpa penguji untuk hasil yang lebih jelek; EZCAD2 membaca
  DXF sama baiknya.

**Batas yang diterima sadar:** DXF **tidak punya pratinjau gambar**, justru
karena kita sengaja tidak mengubahnya jadi polyline. Yang tampil hanya persegi
jejak-kaki di dalam kotak area kerja — cukup untuk menjawab "muat tidak, di mana
letaknya", tidak cukup untuk menilai isinya. Diberi komentar `ponytail:` yang
menyebut jalan naiknya (`ezdxf.path` / `ezdxf.disassemble` untuk meratakan
khusus pratinjau).

`rotate ≠ 0` pada passthrough **tanpa** penskalaan menghasilkan peringatan bahwa
putaran diabaikan — file yang lewat apa adanya memang benar-benar apa adanya.

## Penanganan galat

| Keadaan | Perilaku |
|---|---|
| Satu file gagal di tengah batch | Baris merah, batch lanjut ke file berikutnya |
| Ruang sesi ≥ 200 MB | HTTP 200 `{"ok": false, "error": …}` dengan angka; file tidak diproses |
| Nama tidak sah di `/zip` | HTTP 400, tidak ada arsip yang dibuat |
| DXF tanpa `$INSUNITS` | Ukuran dilaporkan sebagai mm + peringatan eksplisit |
| PLT memakai `PR` | Galat yang menyebut sebabnya, bukan angka yang salah |
| DXF/PLT tanpa geometri | Galat, bukan `0 × 0 mm` |
| Hasil lebih besar dari area kerja | Peringatan + garis merah; tidak pernah memblokir |

## Pengujian

`selfcheck.py` tetap satu-satunya penguji ujung-ke-ujung, tetap tanpa
dependensi baru (tanpa pytest, tanpa httpx), tetap memanggil `app.process()`
langsung agar bug penyambungan parameter di `app.py` ikut tertangkap. Tumbuh
dari 9 menjadi 17 cek. Yang baru, delapan:

- **`check_batch_reset`** — dua `_call` berurutan, `reset=True` lalu
  `reset=False`; **kedua** berkas hasil wajib masih ada di disk. Ini persis
  kelas bug yang akan memakan hasil file pertama tanpa suara.
- **`check_zip`** — arsip memuat tepat nama-nama yang diminta; nama dengan
  pemisah path ditolak.
- **`check_rotate_grayscale`** — hasil 90° sama persis dengan rotasi searah
  jarum jam atas hasil 0°, dan `size_mm` yang dilaporkan ikut tertukar.
- **`check_rotate_mirror_order`** — memakai gambar tak simetris di dua sumbu,
  memastikan putar-lalu-cermin, bukan sebaliknya. Cek ini gagal bila urutannya
  terbalik.
- **`check_rotate_vector`** — memutar bentuk L; sudut yang dikenal wajib pindah
  ke posisi yang benar. Mematok **arah** putaran di jalur vektor, bukan sekadar
  bahwa lebar dan tinggi tertukar.
- **`check_plt_size`** — HPGL sintetis dengan rentang yang diketahui
  (`PU0,0;PD4000,0;PD4000,2000;` = 100 × 50 mm) wajib dilaporkan 100 × 50.
- **`check_dxf_size`** — DXF yang ditulis ezdxf pada ukuran yang diketahui
  wajib terbaca ukurannya.
- **`check_dxf_scale`** — DXF terskala punya lebar yang diminta **dan** tetap
  terpusat di (0,0).

Setiap cek baru wajib **dilihat gagal lebih dulu** terhadap kode sebelum
perbaikan, sesuai praktik paket-paket sebelumnya.

`README.md` diperbarui: batch, preset, daftar lensa, putar, dan perilaku
DXF/PLT.

## Sengaja TIDAK dikerjakan

- **Setelan per file dalam batch** — diputuskan operator: satu set untuk semua.
- **Penulisan HPGL keluar** — PLT terskala keluar sebagai DXF.
- **Perataan DXF untuk pratinjau** — jejak-kaki saja; jalan naiknya dicatat.
- **Preset di server / lintas mesin** — localStorage cukup untuk satu meja.
- **Batch dengan mode campuran** — satu batch, satu mode.
- **Centerline (garis tengah) untuk gambar garis** — nilai mutunya paling besar,
  ongkosnya juga paling besar (perlu skeletonization; modul contrib OpenCV tidak
  ada di `opencv-python-headless`). Siklus tersendiri bila gambar garis mulai
  sering masuk.
