"""
Laser Prep — web app LOKAL untuk menyiapkan file pelanggan jadi import-ready EZCAD2.

Jalankan:  python app.py    lalu buka http://127.0.0.1:8000
- Cabang "Logo → Vektor (MOPA)": JPG/PNG/SVG -> DXF + SVG bersih, skala mm benar.
- Cabang "Foto → Grayscale (Kaca UV)": foto -> PNG grayscale bersih, ukuran fisik benar.

Parameter laser & dithering tetap kamu atur di EZCAD2.
"""
from __future__ import annotations
import os
import re
import shutil
import uuid

import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from prep import (
    process_raster_logo,
    process_svg_input,
    process_photo,
    RASTER_EXT,
    VECTOR_EXT,
    PASSTHROUGH_EXT,
)

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "_out")
os.makedirs(OUT_DIR, exist_ok=True)
SESSION_TTL = 3600  # detik; folder sesi yatim dihapus setelah ini

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


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(BASE, "templates", "index.html"), encoding="utf-8") as f:
        resp = HTMLResponse(f.read())
    # sid baru tiap page load -> refresh = sesi baru, hasil lama jadi yatim & di-GC
    resp.set_cookie("lp_sid", uuid.uuid4().hex, httponly=True, samesite="lax")
    _gc_sessions()
    return resp


@app.post("/process")
async def process(
    lp_sid: str = Cookie(default=""),
    file: UploadFile = File(...),
    job: str = Form(...),                 # "mopa" | "uv"
    width_mm: float = Form(50.0),
    # vektor
    auto_threshold: bool = Form(True),
    threshold: int = Form(128),
    invert: bool = Form(False),
    filter_speckle: int = Form(4),
    # raster
    dpi: int = Form(600),
    remove_bg: bool = Form(False),
    autocontrast: bool = Form(True),
    clahe: bool = Form(False),
    gamma: float = Form(1.0),
):
    sid = re.sub(r"[^a-f0-9]", "", lp_sid)[:32] or uuid.uuid4().hex
    sess_dir = _fresh_session_dir(sid)

    ext = os.path.splitext(file.filename or "")[1].lower()
    stem = _safe_stem(file.filename or "file")
    # Simpan sumber di sess_dir agar preview "sebelum" bisa dilayani lewat /out.
    src_path = os.path.join(sess_dir, f"{stem}{ext}")
    with open(src_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        width_mm = max(1.0, float(width_mm))
    except Exception:
        width_mm = 50.0

    def url(p: str) -> str:
        return f"/out/{sid}/" + os.path.basename(p)

    try:
        if job == "mopa":
            if ext in VECTOR_EXT:
                r = process_svg_input(src_path, sess_dir, stem, target_width_mm=width_mm)
            elif ext in RASTER_EXT:
                r = process_raster_logo(
                    src_path, sess_dir, stem,
                    target_width_mm=width_mm,
                    auto_threshold=auto_threshold,
                    threshold=int(threshold),
                    invert=invert,
                    filter_speckle=int(filter_speckle),
                )
            elif ext in PASSTHROUGH_EXT:
                dest = os.path.join(sess_dir, f"{stem}_copy{ext}")
                shutil.copyfile(src_path, dest)
                return JSONResponse({
                    "ok": True, "job": job, "passthrough": True,
                    "downloads": [{"label": ext.upper().lstrip("."), "url": url(dest)}],
                    "before": None, "after": None,
                    "size_mm": None, "n_paths": None,
                    "warnings": [f"File {ext} sudah vektor/siap import — disalin apa adanya. Set ukuran & parameter di EZCAD2."],
                })
            else:
                raise HTTPException(400, f"Format {ext} tak didukung untuk cabang MOPA.")

            def bust(p):  # cache-buster utk preview
                return url(p) + "?v=" + uuid.uuid4().hex[:6]

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

        elif job == "uv":
            if ext not in RASTER_EXT:
                raise HTTPException(400, f"Cabang Kaca UV butuh gambar raster (JPG/PNG/...). Dapat: {ext}")
            r = process_photo(
                src_path, sess_dir, stem,
                target_width_mm=width_mm, dpi=int(dpi),
                remove_bg=remove_bg, autocontrast=autocontrast,
                clahe=clahe, gamma=float(gamma),
            )

            def bust(p):
                return url(p) + "?v=" + uuid.uuid4().hex[:6]

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
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print("\n  Laser Prep berjalan di:  http://127.0.0.1:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
