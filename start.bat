@echo off
REM Dobel-klik berkas ini untuk menjalankan Laser Prep. Browser terbuka sendiri.
REM Jendela ini HARUS tetap terbuka selama alat dipakai — menutupnya mematikan server.
cd /d "%~dp0"
call venv\Scripts\activate
python app.py
pause
