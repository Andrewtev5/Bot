@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo Pomiar jakosci wyszukiwania...
.venv\Scripts\python.exe -m app.search.evaluate --json docs\wyniki_eksperymentu.json > docs\wyniki_eksperymentu.txt 2>&1
echo Testy automatyczne...
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider > docs\wyniki_testow.txt 2>&1
echo.
echo Gotowe. Wyniki zapisano w folderze docs.
pause
