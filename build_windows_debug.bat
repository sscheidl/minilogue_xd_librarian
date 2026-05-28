@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --console ^
  --name minilogue_xd_librarian_debug ^
  --hidden-import mido.backends.rtmidi ^
  --hidden-import rtmidi ^
  main.py

endlocal
