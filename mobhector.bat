@echo off
setlocal EnableExtensions
title MobHector 1.4.1

set "ROOT=%~dp0"
set "APP=%ROOT%mobhector.pyw"
set "PYROOT=%ROOT%MobHectorRuntime\Python"
set "PYW=%PYROOT%\pythonw.exe"
set "PY=%PYROOT%\python.exe"

if not exist "%APP%" (
    echo [ERROR] No se encontro MobHector:
    echo   %APP%
    echo Ejecuta instalar_mobhector.bat
    pause
    exit /b 1
)

if not exist "%PYW%" (
    echo [ERROR] No se encontro el runtime privado:
    echo   %PYROOT%
    echo Ejecuta instalar_mobhector.bat
    pause
    exit /b 2
)

set "PYTHONUTF8=1"
start "" "%PYW%" "%APP%"
exit /b 0
