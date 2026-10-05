@echo off
REM ANTSDR U220 Spectrum GUI 런처
REM MSYS2 MinGW Python 환경 + UHD Python 바인딩 사용

set MSYS2_PYTHON=C:\msys64\mingw64\bin\python3.exe
set UHD_DLL_DIR=C:\msys64\mingw64\bin
set U220_FPGA=C:\Temp\antsdr_u220_ad9361.bin

"%MSYS2_PYTHON%" -c "import os; os.add_dll_directory('%UHD_DLL_DIR%')" 2>nul

REM U220 FPGA 이미지 경로를 환경 변수로 전달
set U220_FPGA_IMAGE=%U220_FPGA%

"%MSYS2_PYTHON%" "%~dp0u220_spectrum_gui.py"
pause
