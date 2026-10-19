@echo off
setlocal
REM ============================================================
REM  ANTSDR U220 Spectrum GUI launcher
REM  Runs u220_spectrum_gui.py with MSYS2 MinGW Python + UHD
REM ============================================================

REM -- Path configuration --
set MSYS2_PYTHON=C:\msys64\mingw64\bin\python3.exe
set UHD_DLL_DIR=C:\msys64\mingw64\bin
REM If U220_FPGA_IMAGE is not set, usrp_b210_fpga.bin in this folder is used
REM set U220_FPGA_IMAGE=C:\path\to\usrp_b210_fpga.bin
set UHD_LOG_LEVEL=warning

REM -- Check MSYS2 Python exists --
if not exist "%MSYS2_PYTHON%" (
    echo [ERROR] Python not found: %MSYS2_PYTHON%
    echo.
    echo  Edit MSYS2_PYTHON in this script to point to python3.exe
    echo.
    pause
    exit /b 1
)

REM -- Add UHD DLL directory to PATH --
set PATH=%UHD_DLL_DIR%;%PATH%

REM -- Pre-check UHD module --
"%MSYS2_PYTHON%" -c "import uhd" 2>nul
if errorlevel 1 (
    echo [WARN] Failed to import python uhd module.
    echo        UHD_DLL_DIR=%UHD_DLL_DIR%
    echo        Make sure python-uhd is installed in MSYS2:
    echo          pacman -S mingw-w64-x86_64-python-uhd
    echo.
    echo  Press any key to continue anyway. (Ctrl+C to cancel)
    pause
)

REM -- Launch GUI --
echo [INFO] Running: %MSYS2_PYTHON% "%~dp0u220_spectrum_gui.py"
echo.
"%MSYS2_PYTHON%" "%~dp0u220_spectrum_gui.py"

REM -- Show error code on abnormal exit --
if errorlevel 1 (
    echo.
    echo [ERROR] Program exited with code %errorlevel%.
    pause
)
endlocal
