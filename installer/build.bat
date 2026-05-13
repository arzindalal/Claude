@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  ISO 26262 Validation Tool -- Windows Build Script
echo ============================================================
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ from https://python.org
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER%

:: ── Move to repo root ─────────────────────────────────────────────────────────
cd /d "%~dp0.."
echo [INFO] Working directory: %CD%

:: ── Install / upgrade dependencies ───────────────────────────────────────────
echo.
echo [STEP 1/4] Installing Python dependencies...
pip install -r iso26262_validator\requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

echo [STEP 2/4] Installing PyInstaller (latest)...
pip install "pyinstaller>=6.11" --upgrade --quiet
if errorlevel 1 ( echo [ERROR] PyInstaller install failed & pause & exit /b 1 )

:: ── PyInstaller build ─────────────────────────────────────────────────────────
echo.
echo [STEP 3/4] Building executable (this can take 5-15 minutes)...
pyinstaller ISO26262Validator.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    echo         Check the output above for details.
    pause & exit /b 1
)
echo [OK] Executable built: dist\ISO26262Validator\ISO26262Validator.exe

:: ── Inno Setup ────────────────────────────────────────────────────────────────
echo.
echo [STEP 4/4] Building installer...

:: Look for iscc.exe in common Inno Setup locations
set ISCC=
for %%p in (
    "C:\Program Files (x86)\Inno Setup 6\iscc.exe"
    "C:\Program Files\Inno Setup 6\iscc.exe"
    "C:\Program Files (x86)\Inno Setup 5\iscc.exe"
) do (
    if exist %%p ( set ISCC=%%p )
)

if "%ISCC%"=="" (
    echo [WARN] Inno Setup not found -- skipping installer creation.
    echo        Download Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo        Then run:  "%ISCC%" installer\setup.iss
    echo.
    echo Build complete.  Portable app is in: dist\ISO26262Validator\
    pause & exit /b 0
)

if not exist installer_output mkdir installer_output
%ISCC% installer\setup.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup compilation failed.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  Installer: installer_output\ISO26262Validator_Setup_v0.4.0.exe
echo  Portable:  dist\ISO26262Validator\
echo ============================================================
pause
