@echo off
setlocal EnableExtensions
title MobHector 1.5.1 Actualizador QA

cd /d "%~dp0"

echo.
echo ============================================================
echo   MOBHECTOR 1.5.1 - UPDATE ONLY
echo ============================================================
echo.
echo No instala Python ni dependencias.
echo Conserva sesiones, configuracion, known_hosts y credenciales.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0actualizar_mobhector.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [ERROR] Actualizacion fallida.
    echo Revisa el mensaje anterior y el log de MobHector.
    pause
    exit /b %RC%
)

echo [OK] MobHector 1.5.1 actualizado.
echo.
echo Ejecuta:
echo   mobhector
echo.
pause
exit /b 0
