@echo off
setlocal
cd /d "%~dp0"

python tools\bump_build_version.py || exit /b 1

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --console ^
  --name minilogue_xd_librarian_debug ^
  --add-data "assets\minilogue_xd.png;assets" ^
  --hidden-import mido.backends.rtmidi ^
  --hidden-import rtmidi ^
  main.py

endlocal
