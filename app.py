"""
Laser Prep — web app LOKAL untuk menyiapkan file pelanggan jadi import-ready EZCAD2.

Jalankan:  python app.py    lalu buka http://127.0.0.1:8000
- Mode "Ke Vektor (DXF)": JPG/PNG/SVG -> DXF + SVG bersih, skala mm benar.
- Mode "Ke Grayscale (PNG)": foto -> PNG grayscale bersih, ukuran fisik benar.

Parameter laser & dithering tetap kamu atur di EZCAD2.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
import traceback
import uuid
import zipfile

import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from prep import (
    process_raster_logo,
    process_svg_input,
    process_photo,
    RASTER_EXT,
    VECTOR_EXT,
    PASSTHROUGH_EXT,
    read_size,
    render_file_preview,
    scale_to_dxf,
)

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "_out")
os.makedirs(OUT_DIR, exist_ok=True)
# Detik sejak upload terakhir sebelum folder sesi dihapus. Mtime hanya diperbarui saat
# upload, bukan saat preview/download — jadi ini juga batas "berapa lama tab boleh nganggur".
SESSION_TTL = 1800
# Batas total hasil dalam satu folder sesi. _out adalah tmpfs 256 MB; sisanya
# headroom supaya batch berhenti dengan pesan yang jelas, bukan dengan
# "No space left on device" di tengah penulisan berkas.
BATCH_BUDGET = 200 * 1024 * 1024
# Nama berkas yang boleh dikemas ke ZIP: basename polos, tanpa pemisah path.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# Preset & daftar lensa milik browser, dititipkan di sebelah app.py (BUKAN di _out:
# _out adalah tmpfs yang hilang tiap container mati, dan dikosongkan tiap sesi baru).
STATE_PATH = os.path.join(BASE, "state.json")
# Batas ukuran titipan. Preset & lensa hanya belasan angka per entri, jadi 256 KB
# sudah sangat longgar — ini penjaga supaya endpoint tanpa autentikasi tidak bisa
# dipakai menulis berkas sebesar apa pun ke disk.
STATE_MAX = 256 * 1024

app = FastAPI(title="Laser Prep")
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")


def _safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "file"
    return f"{stem}_{uuid.uuid4().hex[:6]}"


def _gc_sessions() -> None:
    """Hapus folder sesi yatim (tab ditutup / server restart)."""
    now = time.time()
    for name in os.listdir(OUT_DIR):
        d = os.path.join(OUT_DIR, name)
        if os.path.isdir(d) and now - os.path.getmtime(d) > SESSION_TTL:
            shutil.rmtree(d, ignore_errors=True)


def _fresh_session_dir(sid: str) -> str:
    """Folder khusus sesi ini, dikosongkan tiap upload baru."""
    d = os.path.join(OUT_DIR, sid)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _dir_size(d: str) -> int:
    """Total byte berkas biasa langsung di dalam d (folder sesi tidak bersarang)."""
    total = 0
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            total += os.path.getsize(p)
    return total


def _salin_terbatas(src, dst_path: str, batas: int) -> bool:
    """Salin `src` ke `dst_path`, berhenti begitu melewati `batas` byte.

    Return True bila muat; False bila melewati batas — potongan yang terlanjur
    ditulis dihapus, jadi folder sesi tidak menyimpan berkas separuh.

    Ukurannya dihitung sendiri sambil menyalin, tidak diambil dari
    UploadFile.size: nilai itu berasal dari header Content-Length kiriman
    browser, yang tidak selalu ada dan tidak dijamin jujur. Tanpa batas di sini,
    satu berkas raksasa lolos begitu saja — cek budget sebelum menulis tak
    pernah bisa menangkapnya karena folder sesi memang masih kosong.
    """
    ditulis = 0
    with open(dst_path, "wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                return True
            ditulis += len(chunk)
            if ditulis > batas:
                break
            out.write(chunk)
    os.remove(dst_path)
    return False


def _pesan_aman(e: Exception) -> str:
    """Pesan galat untuk layar operator; detail utuhnya ke log server.

    ValueError = galat yang DIBUAT alat ini sendiri (lihat prep/): sudah
    berbahasa Indonesia, sudah dijaga bebas path, dan sering satu-satunya
    petunjuk berguna — diteruskan apa adanya. Galat pustaka (cv2/PIL/vtracer)
    berbahasa Inggris dan kerap memuat path lengkap /app/_out/<sid>/... : tak
    berarti buat operator, dan membocorkan id sesi ke layar.
    """
    traceback.print_exc()
    if isinstance(e, ValueError):
        # Penyaringan BASE tetap dipasang: kalau suatu saat ada ValueError
        # pustaka yang lolos ke sini, ia tidak ikut membawa path internal.
        return str(e).replace(OUT_DIR, "").replace(BASE, "")
    return (
        "Gagal memproses berkas ini. Coba berkas lain; detail teknisnya ada di "
        "log server."
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(BASE, "templates", "index.html"), encoding="utf-8") as f:
        resp = HTMLResponse(f.read())
    _gc_sessions()
    return resp


@app.post("/process")
def process(
    # sid datang dari sessionStorage tab pengirim, BUKAN cookie. Cookie berlaku
    # se-browser: membuka tab kedua menimpa sid tab pertama, lalu upload di tab
    # mana pun (reset=True) mengosongkan folder sesi yang sedang dipakai tab
    # satunya — hasil hilang dan tautan unduhnya mati tanpa pesan apa pun.
    lp_sid: str = Form(default=""),
    file: UploadFile = File(...),
    job: str = Form(...),                 # "vector" | "grayscale"
    reset: bool = Form(True),             # True = kosongkan folder sesi (file pertama batch)
    width_mm: float = Form(50.0),
    height_mm: float = Form(0.0),          # 0 = tanpa batas tinggi
    mirror: bool = Form(False),
    rotate: int = Form(0),                # 0 | 90 | 180 | 270
    scale_passthrough: bool = Form(False),   # DXF/PLT hanya diskalakan bila diminta
    # vektor
    auto_threshold: bool = Form(True),
    threshold: int = Form(128),
    invert: bool = Form(False),
    filter_speckle: int = Form(4),
    # raster
    dpi: int = Form(600),
    remove_bg: bool = Form(False),
    autocontrast: bool = Form(True),
    autotrim: bool = Form(True),
    clahe: bool = Form(False),
    gamma: float = Form(1.0),
):
    sid = re.sub(r"[^a-f0-9]", "", lp_sid)[:32] or uuid.uuid4().hex
    if reset:
        sess_dir = _fresh_session_dir(sid)
    else:
        # File ke-2 dan seterusnya dalam satu batch menumpang folder yang sama —
        # mengosongkannya di sini akan memakan hasil file-file sebelumnya.
        sess_dir = os.path.join(OUT_DIR, sid)
        os.makedirs(sess_dir, exist_ok=True)
    _gc_sessions()

    sisa = BATCH_BUDGET - _dir_size(sess_dir)
    if sisa <= 0:
        # Status 200, bukan 500: ini kondisi yang diharapkan, bukan kesalahan
        # server, dan gelung batch di browser merendernya lewat jalur galat
        # yang sama dengan galat lain.
        return JSONResponse({
            "ok": False,
            "error": f"Ruang hasil penuh ({BATCH_BUDGET // (1024 * 1024)} MB). "
                     f"File ini tidak diproses — unduh hasil yang sudah ada, "
                     f"lalu proses sisanya sebagai batch baru.",
        })

    ext = os.path.splitext(file.filename or "")[1].lower()
    stem = _safe_stem(file.filename or "file")
    # Simpan sumber di sess_dir agar preview "sebelum" bisa dilayani lewat /out.
    src_path = os.path.join(sess_dir, f"{stem}{ext}")
    if not _salin_terbatas(file.file, src_path, sisa):
        return JSONResponse({
            "ok": False,
            "error": f"Berkas ini lebih besar dari sisa ruang hasil "
                     f"({sisa / (1024 * 1024):.1f} MB dari jatah "
                     f"{BATCH_BUDGET // (1024 * 1024)} MB) — tidak diproses. "
                     f"Unduh hasil yang sudah ada lalu proses sisanya sebagai "
                     f"batch baru, atau kecilkan berkasnya dulu.",
        })

    try:
        width_mm = max(1.0, float(width_mm))
    except Exception:
        width_mm = 50.0

    try:
        height_mm = max(0.0, float(height_mm))
    except Exception:
        height_mm = 0.0
    target_h = height_mm if height_mm > 0 else None

    try:
        rotate = int(rotate) % 360
    except Exception:
        rotate = 0
    if rotate not in (90, 180, 270):
        rotate = 0

    def url(p: str) -> str:
        return f"/out/{sid}/" + os.path.basename(p)

    def bust(p: str) -> str:  # cache-buster utk preview
        return url(p) + "?v=" + uuid.uuid4().hex[:6]

    def pratinjau_vektor(berkas: str) -> str | None:
        """Pratinjau untuk berkas DXF/PLT yang benar-benar dikirim ke operator.

        Gagal menggambar TIDAK menggagalkan permintaan — berkasnya sendiri sudah
        benar, dan pratinjau yang hilang jauh lebih murah daripada berkas yang
        batal diproses.
        """
        png = os.path.join(sess_dir, f"{stem}_after.png")
        try:
            return bust(png) if render_file_preview(berkas, png) else None
        except Exception:
            traceback.print_exc()   # ke log server; operator tak perlu tahu
            return None

    try:
        if job == "vector":
            if ext in VECTOR_EXT:
                r = process_svg_input(
                    src_path, sess_dir, stem,
                    target_width_mm=width_mm, target_height_mm=target_h,
                    mirror=mirror,
                    rotate=rotate,
                )
            elif ext in RASTER_EXT:
                r = process_raster_logo(
                    src_path, sess_dir, stem,
                    target_width_mm=width_mm,
                    target_height_mm=target_h,
                    mirror=mirror,
                    rotate=rotate,
                    auto_threshold=auto_threshold,
                    threshold=int(threshold),
                    invert=invert,
                    filter_speckle=int(filter_speckle),
                )
            elif ext in PASSTHROUGH_EXT:
                # Cermin tidak pernah diterapkan pada berkas DXF/PLT kiriman
                # pelanggan — baik diskalakan maupun tidak — jadi cek ini satu
                # tempat saja, dipakai kedua jalur di bawah supaya operator
                # tidak dapat dua peringatan yang sama.
                peringatan_mirror = []
                if mirror:
                    peringatan_mirror.append(
                        "Cermin tidak diterapkan pada berkas vektor kiriman ini "
                        "(DXF/PLT), baik yang diskalakan maupun yang disalin apa "
                        "adanya. Cermin objeknya di EZCAD2 setelah import."
                    )

                if scale_passthrough:
                    out_dxf = os.path.join(sess_dir, f"{stem}_scaled.dxf")
                    size = scale_to_dxf(
                        src_path, out_dxf,
                        target_width_mm=width_mm,
                        target_height_mm=target_h,
                        rotate=rotate,
                    )
                    peringatan = list(peringatan_mirror)
                    if ext == ".plt":
                        peringatan.append(
                            "PLT yang diskalakan keluar sebagai DXF — EZCAD2 membacanya "
                            "sama baiknya, dan geometrinya sudah dipusatkan di (0,0)."
                        )
                    return JSONResponse({
                        "ok": True, "job": job, "passthrough": False,
                        "downloads": [{"label": "DXF terskala (mm)", "url": url(out_dxf)}],
                        # Yang dipratinjau adalah berkas HASIL, bukan sumbernya:
                        # itulah yang benar-benar masuk mesin, lengkap dengan
                        # putaran dan skalanya.
                        "before": None, "after": pratinjau_vektor(out_dxf),
                        "size_mm": [round(size[0], 2), round(size[1], 2)],
                        "n_paths": None,
                        "warnings": peringatan,
                    })

                # Tidak diskalakan: berkas disajikan APA ADANYA — itulah gunanya
                # passthrough. Yang berubah hanyalah alat kini memberi tahu ukurannya.
                w_mm, h_mm, peringatan = read_size(src_path)
                peringatan = list(peringatan) + peringatan_mirror
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
                    "before": None, "after": pratinjau_vektor(src_path),
                    "size_mm": [round(w_mm, 2), round(h_mm, 2)],
                    "n_paths": None,
                    "warnings": peringatan,
                })
            else:
                raise HTTPException(400, f"Format {ext} tak didukung untuk mode Vektor.")

            return JSONResponse({
                "ok": True, "job": job, "passthrough": False,
                "downloads": [
                    {"label": "DXF (utama, mm)", "url": url(r.dxf_path)},
                    {"label": "SVG", "url": url(r.svg_path)},
                ],
                "before": bust(r.preview_before),
                "after": bust(r.preview_after),
                "size_mm": [round(r.size_mm[0], 2), round(r.size_mm[1], 2)],
                "n_paths": r.n_paths,
                "warnings": r.warnings,
            })

        elif job == "grayscale":
            if ext not in RASTER_EXT:
                raise HTTPException(400, f"Mode Grayscale butuh gambar raster (JPG/PNG/TIFF). Dapat: {ext}")
            r = process_photo(
                src_path, sess_dir, stem,
                target_width_mm=width_mm, target_height_mm=target_h, dpi=int(dpi),
                remove_bg=remove_bg, autocontrast=autocontrast, autotrim=autotrim,
                clahe=clahe, gamma=float(gamma), invert=invert,
                mirror=mirror,
                rotate=rotate,
            )
            os.remove(src_path)  # sumber tak dipakai lagi; preview 'before' sudah punya thumbnail sendiri

            return JSONResponse({
                "ok": True, "job": job, "passthrough": False,
                "downloads": [{"label": f"PNG grayscale ({r.px[0]}x{r.px[1]} @ {r.dpi}dpi)", "url": url(r.png_path)}],
                "before": bust(r.preview_before),
                "after": bust(r.preview_after),
                "size_mm": [round(r.size_mm[0], 2), round(r.size_mm[1], 2)],
                "n_paths": None,
                "warnings": r.warnings,
            })
        else:
            raise HTTPException(400, "Job tidak dikenal.")
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"ok": False, "error": _pesan_aman(e)}, status_code=500)


@app.post("/zip")
def zip_outputs(lp_sid: str = Body(default=""), names: list[str] = Body(...)):
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
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
            for p in paths:
                z.write(p, arcname=os.path.basename(p))
    except Exception:
        # Penulisan gagal di tengah (mis. berkas terhapus GC sesi sebelum sempat
        # dibaca) -> BackgroundTask tak pernah terpasang, jadi arsip parsial
        # dibersihkan di sini juga, bukan hanya pada jalur sukses. Galat
        # penghapusan sendiri diabaikan: kegagalan ASLI yang perlu dilaporkan
        # adalah galat penulisan ZIP, bukan urusan bersih-bersihnya.
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        raise
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"laser-prep-{sid[:6]}.zip",
        background=BackgroundTask(os.remove, tmp.name),
    )


@app.get("/state")
def baca_state():
    """Setelan milik browser (preset + daftar lensa) yang dititipkan ke server.

    Isinya TIDAK pernah ditafsirkan di sini — server cuma tempat penitipan, dan
    bentuk datanya urusan index.html sepenuhnya. Sebelum ini keduanya hidup di
    localStorage: hilang begitu operator membersihkan data situs, dan tak
    terlihat dari browser atau komputer lain.
    """
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return JSONResponse(json.load(f))
    except FileNotFoundError:
        return JSONResponse({})
    except (json.JSONDecodeError, OSError):
        # state.json rusak (diedit tangan / tulis terpotong saat mati listrik)
        # tidak boleh mematikan alatnya: operator kehilangan preset, bukan
        # kemampuan memproses berkas.
        traceback.print_exc()
        return JSONResponse({})


@app.post("/state")
def tulis_state(state: dict = Body(...)):
    isi = json.dumps(state)
    if len(isi.encode("utf-8")) > STATE_MAX:
        raise HTTPException(
            413, f"Setelan terlalu besar (maks {STATE_MAX // 1024} KB)."
        )
    # Tulis ke berkas sementara lalu ganti nama: os.replace bersifat atomik, jadi
    # mati listrik di tengah penulisan menyisakan state LAMA yang utuh, bukan
    # state.json separuh yang tak bisa dibaca.
    #
    # Nama sementaranya WAJIB unik per permintaan. Satu aksi operator memicu dua
    # simpan berurutan (mis. preset lalu lensa), keduanya dilayani di threadpool
    # sekaligus: dengan satu nama tetap, keduanya menulis ke berkas yang sama —
    # isinya berselang-seling jadi JSON rusak, lalu os.replace yang kalah cepat
    # gagal dengan FileNotFoundError. Terbukti terjadi pada pemakaian biasa,
    # bukan skenario karangan.
    tmp = f"{STATE_PATH}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(isi)
        os.replace(tmp, STATE_PATH)
    except OSError:
        # Disk penuh / tak bisa ditulis: jangan tinggalkan berkas .tmp yatim yang
        # menumpuk tiap kegagalan.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import threading
    import uvicorn
    import webbrowser

    url = "http://127.0.0.1:8000"
    print(f"\n  Laser Prep berjalan di:  {url}\n")
    # Buka browser sendiri: operator dobel-klik start.bat, alatnya langsung siap.
    # Timer, bukan panggilan langsung — uvicorn.run memblokir, jadi baris setelahnya
    # tak akan pernah jalan. 1 detik cukup untuk server siap menerima.
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
