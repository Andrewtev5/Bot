@echo off
cd /d "%~dp0"

set HOST=26.33.72.14
set PORT=8001
set ALLOWED_ORIGINS=http://26.33.72.14,http://127.0.0.1,http://localhost,http://127.0.0.1:8000,http://localhost:8000
set ALLOWED_ORIGIN_REGEX=^https?://(127\.0\.0\.1^|localhost^|26\.33\.72\.14)(:\d+)?$

python -m uvicorn app.main:app --host 26.33.72.14 --port 8001 --reload
