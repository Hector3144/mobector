Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:USERPROFILE 'bin'
Write-Host 'Se eliminarán sólo archivos de MobHector. Sesiones, credenciales y respaldos se conservan.'
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -like '*mobhector.pyw*' })
if ($running.Count -gt 0) { throw 'Cierra MobHector antes de desinstalar.' }
if ((Read-Host 'Escribe DESINSTALAR para continuar') -cne 'DESINSTALAR') { exit 0 }
$manifest = Join-Path $InstallDir 'MANIFEST_SHA256.txt'
if (-not (Test-Path -LiteralPath $manifest)) { throw 'Falta el registro de archivos instalados. No se borrará la carpeta bin.' }
$files = @('MANIFEST_SHA256.txt', 'MANIFEST_FULL_SHA256.txt')
foreach ($line in Get-Content -LiteralPath $manifest) {
    if ($line -notmatch '^[0-9a-f]{64}  (.+)$') { throw 'Registro de archivos inválido.' }
    $relative = $Matches[1].Replace('/', '\')
    if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or $relative -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Ruta insegura en el registro.' }
    if ([IO.Path]::GetFileName($relative) -in @('config.json', 'known_hosts')) { throw 'Datos de usuario en el registro; se aborta.' }
    $owned = @('mobhector.pyw', 'transfer_engine.py', 'credential_store.py', 'host_key_store.py',
        'x11_forwarding.py', 'terminal_io.py', 'session_validation.py', 'remote_text.py', 'install_support.py', 'requirements.txt',
        'requirements-windows.lock', 'VERSION.txt', 'mobhector.bat', 'mobhector_debug.bat',
        'rusterfiles.bat', 'actualizar_mobhector.bat', 'actualizar_mobhector.ps1',
        'desinstalar_mobhector.bat', 'desinstalar_mobhector.ps1',
        'assets\xterm.js', 'assets\xterm.css', 'assets\xterm-addon-fit.js', 'assets\terminal.html',
        'assets\LICENSE-xterm.txt', 'assets\LICENSE-xterm-addon-fit.txt')
    if ($relative -in $owned -or $relative.StartsWith('vendor\vcxsrv\')) { $files += $relative }
}
foreach ($relative in $files) {
    $path = Join-Path $InstallDir $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -Force -LiteralPath $path }
}
Remove-Item -Recurse -Force -LiteralPath (Join-Path $InstallDir 'MobHectorRuntime') -ErrorAction SilentlyContinue
$desktop = [Environment]::GetFolderPath('Desktop')
Remove-Item -Force -LiteralPath (Join-Path $desktop 'MobHector.lnk') -ErrorAction SilentlyContinue
$programs = [Environment]::GetFolderPath('Programs')
Remove-Item -Force -LiteralPath (Join-Path $programs 'MobHector\MobHector.lnk') -ErrorAction SilentlyContinue
Write-Host 'MobHector eliminado. Los datos del usuario permanecen en APPDATA y LOCALAPPDATA.' -ForegroundColor Green
