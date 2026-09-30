@echo off
setlocal EnableExtensions
if exist "%USERPROFILE%\bin\mobhector.pyw" (
    call "%~dp0actualizar_mobhector.bat"
) else (
    call "%~dp0instalar_mobhector.bat"
)
exit /b %ERRORLEVEL%
