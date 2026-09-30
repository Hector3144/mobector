@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title MobHector 1.4.1 - Instalador completo

echo ============================================================
echo   MOBHECTOR 1.4.1 - INSTALADOR COMPLETO PARA WINDOWS x64
echo ============================================================
echo.
echo Instala runtime Python privado, dependencias y accesos directos.
echo No cambia la politica de ejecucion de PowerShell.
echo No incluye sesiones ni credenciales de otro usuario.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_mobhector.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [ERROR] Instalacion fallida. Revisa el mensaje y el log anterior.
) else (
    echo [OK] Instalacion terminada.
)
pause
exit /b %RC%
