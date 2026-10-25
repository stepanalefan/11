@echo off
REM Build UltimateVideoDownloader.exe locally on Windows.
REM Optional: put ffmpeg.exe and ffprobe.exe in this folder to bundle them.
cd /d "%~dp0"
python -m pip install -U pip pyinstaller -r requirements.txt || exit /b 1
set EXTRA=
if exist ffmpeg.exe set EXTRA=--add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;."
pyinstaller --noconfirm --clean --onefile --noconsole --name UltimateVideoDownloader ^
  --icon icon.ico --collect-submodules yt_dlp %EXTRA% ytdlp_gui.py || exit /b 1
echo.
echo Built: %~dp0dist\UltimateVideoDownloader.exe
