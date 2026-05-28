@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  packaging\pyinstaller\minilogue_xd_librarian.spec

endlocal
