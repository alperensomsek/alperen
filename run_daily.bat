@echo off
REM ALgpt'yi bu bilgisayarda calistirir (Gorev Zamanlayici bunu her gun cagirir).
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
python main.py >> "logs\run.log" 2>&1
