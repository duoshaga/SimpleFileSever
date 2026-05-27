@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --windowed --onefile --name "文件服务器" app.py
pause
