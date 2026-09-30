@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title MobHector - Desinstalador
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar_mobhector.ps1"
echo.
pause
