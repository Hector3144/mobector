@echo off
setlocal EnableExtensions
title MobHector 1.5.1 - DEBUG

set "ROOT=%~dp0"
set "PY=%ROOT%MobHectorRuntime\Python\python.exe"
set "APP=%ROOT%mobhector.pyw"

if not exist "%PY%" (
    echo [ERROR] Runtime Python no encontrado.
    pause
    exit /b 2
)

set "PYTHONUTF8=1"
"%PY%" "%APP%"
echo.
echo Codigo de salida: %ERRORLEVEL%
pause
