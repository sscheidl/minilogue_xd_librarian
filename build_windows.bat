@echo off
setlocal
cd /d "%~dp0"

python tools\bump_build_version.py || exit /b 1

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  packaging\pyinstaller\minilogue_xd_librarian.spec

endlocal
