@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Build onefile - Frost Forecaster Simple
echo ==========================================

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name FrostForecasterSimple ^
  --collect-all matplotlib ^
  main.pyw

if errorlevel 1 (
  echo.
  echo ERRO no build.
  pause
  exit /b 1
)

echo.
echo Build concluido:
echo   dist\FrostForecasterSimple.exe
echo.
explorer dist
pause
