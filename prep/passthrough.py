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

PLT_UNIT_MM = 0.025          # 1 satuan plotter HPGL = 0.025 mm (40 satuan/mm)

# $INSUNITS DXF -> faktor ke mm. Kunci yang tidak ada di sini adalah satuan yang
# ALAT INI tidak kenali (bukan berarti berkasnya tak menyatakan satuan) —
# angkanya dipakai apa adanya, disertai peringatan yang membedakan dua kasus itu.
_INSUNITS_MM = {
    1: 25.4,      # inci
    2: 304.8,     # kaki
    4: 1.0,       # mm
    5: 10.0,      # cm
    6: 1000.0,    # meter
    9: 0.0254,    # mil (seperseribu inci)
    10: 914.4,    # yard
    13: 0.001,    # mikron
    14: 100.0,    # desimeter
}

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
        if c == "SC":
            raise ValueError(
                "File PLT memakai SC (Scale) — perintah ini memetakan ulang unit "
                "pengguna ke unit plotter, jadi koordinat di berkas ini TIDAK bisa "
                "dibaca langsung sebagai satuan plotter tanpa salah ukuran. Belum "
                "didukung. Ekspor ulang dari sumbernya tanpa SC, atau kirim DXF."
            )
        if c == "IP":
            raise ValueError(
                "File PLT memakai IP (Input P1/P2) — perintah ini menggeser titik "
                "acuan koordinat plotter, jadi ukuran yang terbaca bisa salah tanpa "
                "peringatan. Belum didukung. Ekspor ulang dari sumbernya tanpa IP, "
                "atau kirim DXF."
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


def _cek_log_transform(log: "ezdxf.transform.Logger") -> None:
    """ezdxf.transform (z_rotate/scale_uniform/translate) TIDAK melempar galat
    untuk entitas yang gagal ditransformasi -- ia mencatatnya ke Logger dan
    membiarkan entitas itu apa adanya, dokumentasinya eksplisit soal ini. Diam-
    diam salah (geometri campur skala, sebagian belum diputar) jauh lebih mahal
    daripada berhenti -- sikap yang sama sudah dipakai untuk PLT ber-PR."""
    if len(log):
        raise ValueError(
            f"{len(log)} entitas dalam file DXF ini tidak bisa diputar/diskalakan/"
            "dipindah (kemungkinan objek yang tidak didukung, mis. OLE atau "
            "proxy). Buka di CAD lain untuk membersihkannya, lalu kirim ulang."
        )


def _read_dxf(path: str):
    """ezdxf.readfile, tapi galatnya diterjemahkan: pesan asli berbahasa Inggris
    dan memuat path absolut di dalam container (termasuk id sesi) -- keduanya
    tak berguna buat operator dan yang kedua bocor info internal ke layar."""
    try:
        return ezdxf.readfile(path)
    except Exception as e:
        raise ValueError(
            "File DXF tidak bisa dibaca — kemungkinan rusak, atau sebenarnya "
            "bukan DXF (mis. .dwg yang diganti nama jadi .dxf). Ekspor ulang "
            "dari sumbernya, atau minta pelanggan mengirim ulang."
        ) from e


def read_size(path: str) -> Tuple[float, float, List[str]]:
    """(lebar_mm, tinggi_mm, warnings) untuk berkas .dxf atau .plt."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".plt":
        box = _bbox(plt_to_polylines(path))
        if box is None:
            raise ValueError("File PLT tidak memuat garis yang bisa dibaca.")
        return box[2] - box[0], box[3] - box[1], []

    if ext == ".dxf":
        doc = _read_dxf(path)
        x0, y0, x1, y1 = _dxf_extents(doc)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
        faktor = _INSUNITS_MM.get(insunits)
        warnings: List[str] = []
        if faktor is None:
            faktor = 1.0
            if insunits == 0:
                # $INSUNITS=0: berkas MEMANG tidak menyatakan satuannya sama sekali.
                warnings.append(
                    "File DXF tidak menyatakan satuannya ($INSUNITS=0) — ukuran di atas "
                    "dianggap milimeter. Periksa di EZCAD2 bila terasa janggal."
                )
            else:
                # $INSUNITS != 0: berkas MENYATAKAN satuannya dengan jelas, alat
                # ini saja yang belum mengenali kode itu -- jangan menuduh berkasnya.
                warnings.append(
                    f"File DXF menyatakan satuan $INSUNITS={insunits}, tapi alat ini "
                    "belum mengenali kode satuan itu — ukuran di atas dianggap milimeter "
                    "apa adanya (bisa jauh meleset). Periksa di EZCAD2 bila terasa janggal."
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
    doc = _read_dxf(src_path)
    # list(...) bukan modelspace-nya langsung: helper ezdxf.transform menerima
    # Iterable[DXFEntity], dan daftar konkret menghilangkan pertanyaan apakah
    # iterasi tetap sah sementara entitasnya sedang diubah.
    msp = list(doc.modelspace())

    if rotate in (90, 180, 270):
        # ezdxf memutar berlawanan jarum jam untuk sudut positif; kita ingin
        # searah jarum jam, arah yang sama dengan rotate_polylines dan cv2.rotate.
        _cek_log_transform(ezdxf.transform.z_rotate(msp, -math.radians(rotate)))

    x0, y0, x1, y1 = _dxf_extents(doc)
    src_w, src_h = x1 - x0, y1 - y0
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Geometri DXF merosot (lebar atau tinggi nol).")

    # Faktor dihitung dari koordinat MENTAH, dan doc.units dipaksa MM di bawah:
    # dengan begitu satuan asal file tidak ikut masuk hitungan dua kali.
    faktor = target_width_mm / src_w
    if target_height_mm:
        faktor = min(faktor, target_height_mm / src_h)
    _cek_log_transform(ezdxf.transform.scale_uniform(msp, faktor))

    x0, y0, x1, y1 = _dxf_extents(doc)
    _cek_log_transform(
        ezdxf.transform.translate(msp, (-(x0 + x1) / 2, -(y0 + y1) / 2, 0))
    )

    doc.units = ezunits.MM
    doc.saveas(out_path)

    # Ukuran yang dilaporkan diukur ULANG dari bbox berkas yang benar-benar
    # ditulis, bukan dihitung dari src_w * faktor -- kalau ada entitas yang
    # gagal ditransformasi (ditangkap di atas) atau perilaku transform berubah,
    # angka yang sampai ke operator tetap sesuai isi berkas, bukan asumsi.
    x0, y0, x1, y1 = _dxf_extents(doc)
    return x1 - x0, y1 - y0


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

        # SC (Scale) memetakan ulang unit pengguna ke unit plotter -- diabaikan
        # diam-diam, koordinatnya salah tanpa peringatan. Harus BERHENTI, sama
        # seperti PR.
        sc = os.path.join(d, "sc.plt")
        with open(sc, "w") as f:
            f.write("IN;SC0,100,0,100;PU0,0;PD100,100;")
        try:
            read_size(sc)
        except ValueError as e:
            assert "sc" in str(e).lower(), str(e)
        else:
            raise AssertionError("PLT dengan SC seharusnya menaikkan galat")

        # IP (Input P1/P2) menggeser titik acuan koordinat -- sama bahayanya.
        ip = os.path.join(d, "ip.plt")
        with open(ip, "w") as f:
            f.write("IN;IP500,500,5500,5500;PU0,0;PD100,100;")
        try:
            read_size(ip)
        except ValueError as e:
            assert "ip" in str(e).lower(), str(e)
        else:
            raise AssertionError("PLT dengan IP seharusnya menaikkan galat")

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
        assert "tidak menyatakan" in warn[0].lower(), warn  # $INSUNITS=0: berkas MEMANG tak menyatakan

        # --- DXF dalam mil ($INSUNITS=9): berkas MENYATAKAN satuannya dengan
        # jelas -- tanpa dukungan mil, ukuran akan meleset ~39x (0.0254 vs 1.0).
        # Sama seperti kasus inci: tanpa warning, karena satuannya DIKENALI.
        doc_mil = ezdxf.new("R2010")
        doc_mil.header["$INSUNITS"] = 9
        doc_mil.modelspace().add_lwpolyline([(0, 0), (2000, 0), (2000, 1000), (0, 1000)], close=True)
        dxf_mil = os.path.join(d, "mil.dxf")
        doc_mil.saveas(dxf_mil)
        w, h, warn = read_size(dxf_mil)
        assert abs(w - 50.8) < 1e-6 and abs(h - 25.4) < 1e-6, (w, h)
        assert warn == [], warn

        # --- DXF dengan $INSUNITS dikenal DXF tapi tak dikenal ALAT INI (mis. 3
        # = mil per spec DXF lama / satuan lain di luar tabel kita). Pesannya
        # WAJIB menyebut kode aslinya dan bilang "belum mengenali", BUKAN
        # "tidak menyatakan" -- berkasnya sudah jujur soal satuan, alat yang
        # kurang tahu.
        doc_x = ezdxf.new("R2010")
        doc_x.header["$INSUNITS"] = 3
        doc_x.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 4), (0, 4)], close=True)
        dxf_x = os.path.join(d, "x.dxf")
        doc_x.saveas(dxf_x)
        w, h, warn = read_size(dxf_x)
        assert abs(w - 10.0) < 1e-6 and abs(h - 4.0) < 1e-6, (w, h)
        assert warn, "satuan tak dikenal seharusnya tetap memberi peringatan"
        assert "$insunits=3" in warn[0].lower(), warn
        assert "belum mengenali" in warn[0].lower(), warn
        assert "tidak menyatakan" not in warn[0].lower(), (
            "berkas ber-$INSUNITS=3 MENYATAKAN satuannya -- jangan bilang ia tak menyatakan apa-apa: "
            + warn[0]
        )

        # --- DXF rusak (bukan DXF sama sekali): pesan galat wajib Indonesia,
        # tanpa path absolut container di dalamnya.
        rusak = os.path.join(d, "rusak.dxf")
        with open(rusak, "w") as f:
            f.write("ini bukan DXF sama sekali, cuma teks biasa")
        try:
            read_size(rusak)
        except ValueError as e:
            pesan = str(e)
            assert rusak not in pesan, f"pesan galat membocorkan path internal: {pesan}"
            assert "/" not in pesan, f"pesan galat memuat path: {pesan}"
            assert "dxf" in pesan.lower(), pesan
        else:
            raise AssertionError("DXF rusak seharusnya menaikkan ValueError")
        try:
            scale_to_dxf(rusak, os.path.join(d, "rusak_out.dxf"), target_width_mm=40.0)
        except ValueError as e:
            assert rusak not in str(e), f"pesan galat membocorkan path internal: {e}"
        else:
            raise AssertionError("scale_to_dxf atas DXF rusak seharusnya menaikkan ValueError")

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

        # --- Arah rotasi DXF: bujur sangkar di atas simetris, bbox-nya SAMA
        # untuk CW maupun CCW -- itu tidak membuktikan arahnya benar. Pakai
        # bentuk L asimetris: garis panjang menunjuk KANAN (+x), garis pendek
        # menunjuk ATAS (+y) cuma supaya bbox tidak merosot (tinggi > 0).
        doc_dir = ezdxf.new("R2010")
        doc_dir.units = ezunits.MM
        doc_dir.modelspace().add_line((0, 0), (20, 0))   # penanda arah
        doc_dir.modelspace().add_line((0, 0), (0, 5))    # cuma beri tinggi
        dxf_dir = os.path.join(d, "dir.dxf")
        doc_dir.saveas(dxf_dir)

        out_dir = os.path.join(d, "dir_out.dxf")
        scale_to_dxf(dxf_dir, out_dir, target_width_mm=60.0, rotate=90)
        garis = list(ezdxf.readfile(out_dir).modelspace().query("LINE"))
        # garis penanda = yang terpanjang (skala seragam menjaga rasio panjang)
        penanda = max(garis, key=lambda e: e.dxf.start.distance(e.dxf.end))
        dx = penanda.dxf.end.x - penanda.dxf.start.x
        dy = penanda.dxf.end.y - penanda.dxf.start.y
        # Patok TANDA & SUMBU, bukan angka absolut -- keluarannya diskalakan
        # dan dipusatkan di (0,0), jadi magnitudonya tidak bisa ditebak persis.
        # Garis yang semula menunjuk KANAN (+x) harus mendarat menunjuk BAWAH
        # (-y) untuk putaran SEARAH JARUM JAM (sama seperti rotate_polylines).
        assert abs(dx) < 1e-6 and dy < -1e-6, (
            f"arah rotasi DXF salah, garis kanan harus mendarat menunjuk "
            f"bawah: dx={dx}, dy={dy}"
        )

        # --- PLT yang diskalakan keluar sebagai DXF ---
        outp = os.path.join(d, "p.dxf")
        sizep = scale_to_dxf(p, outp, target_width_mm=200.0)
        assert abs(sizep[0] - 200.0) < 1e-3 and abs(sizep[1] - 100.0) < 1e-2, sizep

        # --- DXF tanpa geometri sama sekali = galat, bukan ukuran 0 x 0 ---
        doc_kosong = ezdxf.new("R2010")
        dxf_kosong = os.path.join(d, "kosong.dxf")
        doc_kosong.saveas(dxf_kosong)
        try:
            read_size(dxf_kosong)
        except ValueError as e:
            assert "geometri" in str(e).lower(), str(e)
        else:
            raise AssertionError("DXF tanpa geometri seharusnya menaikkan galat")

        # --- ARC harus tetap ARC setelah scale_to_dxf, bukan diratakan jadi
        # polyline -- itulah alasan jalur DXF memakai ezdxf.transform, bukan
        # fit_polylines/write_dxf seperti jalur PLT.
        doc_arc = ezdxf.new("R2010")
        doc_arc.units = ezunits.MM
        doc_arc.modelspace().add_arc(center=(10, 10), radius=5, start_angle=0, end_angle=90)
        dxf_arc = os.path.join(d, "arc.dxf")
        doc_arc.saveas(dxf_arc)
        out_arc = os.path.join(d, "arc_out.dxf")
        scale_to_dxf(dxf_arc, out_arc, target_width_mm=40.0)
        msp_arc = ezdxf.readfile(out_arc).modelspace()
        assert len(list(msp_arc.query("ARC"))) == 1, "ARC harus tetap ARC, bukan diratakan"
        assert len(list(msp_arc.query("LWPOLYLINE"))) == 0, "ARC tidak boleh berubah jadi LWPOLYLINE"

        # --- Entitas yang gagal ditransformasi (ezdxf.transform TIDAK melempar
        # galat untuknya, cuma mencatat ke Logger) harus menghentikan
        # scale_to_dxf, bukan lolos diam-diam dengan geometri campur skala.
        # OLE2FRAME dipakai sebagai entitas nyata yang transform()-nya memang
        # NotImplementedError di ezdxf 1.4.4 (diverifikasi lewat probe).
        doc_ole = ezdxf.new("R2010")
        doc_ole.units = ezunits.MM
        doc_ole.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        doc_ole.modelspace().new_entity("OLE2FRAME", dxfattribs={})
        dxf_ole = os.path.join(d, "ole.dxf")
        doc_ole.saveas(dxf_ole)
        try:
            scale_to_dxf(dxf_ole, os.path.join(d, "ole_out.dxf"), target_width_mm=40.0)
        except ValueError as e:
            assert "transformasi" in str(e).lower() or "diputar" in str(e).lower(), str(e)
        else:
            raise AssertionError(
                "DXF dengan entitas yang gagal ditransformasi (OLE2FRAME) "
                "seharusnya menaikkan ValueError, bukan lolos diam-diam"
            )

    print("ok")
