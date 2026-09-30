Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:USERPROFILE 'bin'
$PythonExe = Join-Path $InstallDir 'MobHectorRuntime\Python\python.exe'
$BackupRoot = Join-Path $env:LOCALAPPDATA 'MobHector\Backups'
try {
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'No hay instalación previa. Ejecuta instalar_mobhector.bat.' }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -like '*mobhector.pyw*'
    })
    if ($running.Count -gt 0) { throw 'Cierra MobHector y vuelve a ejecutar la actualización.' }
    & $PythonExe (Join-Path $SourceDir 'install_support.py') $SourceDir $InstallDir $BackupRoot
    if ($LASTEXITCODE -ne 0) { throw 'La actualización falló. Revisa el resultado y la ubicación del respaldo.' }
    Write-Host 'MobHector 1.4.1 actualizado. Sesiones y credenciales conservadas.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
