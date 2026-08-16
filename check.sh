#!/bin/sh
# Semua cek Laser Prep dalam satu perintah.
#
#   docker compose run --rm --no-deps laser-prep ./check.sh
#
# Sebelum ini keempatnya harus diingat satu per satu dan README cuma menyebut
# selfcheck.py — cek modul yang terlewat tidak akan pernah ketahuan gagal.
#
# -W ignore::RuntimeWarning: `python -m prep.x` memperingatkan bahwa prep/x sudah
# diimpor duluan oleh prep/__init__.py. Tak berbahaya, tapi peringatan yang
# muncul di SETIAP kali jalan melatih orang mengabaikan peringatan.
set -e

python -W ignore::RuntimeWarning -m prep.geometry
python -W ignore::RuntimeWarning -m prep.vector
python -W ignore::RuntimeWarning -m prep.passthrough
python selfcheck.py

# prep/raster.py tak punya self-check sendiri: seluruh jalurnya (trim, kontras,
# gamma, CLAHE, hapus latar, skala mm) sudah ditempuh selfcheck.py lewat endpoint.
echo "semua cek lolos"
