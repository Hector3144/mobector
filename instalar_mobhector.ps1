Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$AppVersion = "1.5.1"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:USERPROFILE "bin"
$RuntimeDir = Join-Path $InstallDir "MobHectorRuntime"
$PythonDir = Join-Path $RuntimeDir "Python"
$PythonExe = Join-Path $PythonDir "python.exe"
$PythonwExe = Join-Path $PythonDir "pythonw.exe"
$InstalledApp = Join-Path $InstallDir "mobhector.pyw"
$LogDir = Join-Path $env:LOCALAPPDATA "MobHector\Logs"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "install-$AppVersion-$Stamp.log"
$TempRoot = Join-Path $env:TEMP "MobHectorInstaller-$Stamp"
$FreshCopyStarted = $false
$FullManifest = Join-Path $SourceDir "MANIFEST_FULL_SHA256.txt"

$PythonCandidates = @(
    @{ Version = "3.13.14"; Url = "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe" }
)

function Step([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
}

function Run-C {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Download-File {
    param(
        [Parameter(Mandatory=$true)][string[]]$Urls,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$Label
    )

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $lastError = $null

    foreach ($url in $Urls) {
        try {
            Write-Host "  Descargando $Label..." -ForegroundColor Gray
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination -TimeoutSec 180
            $size = (Get-Item -LiteralPath $Destination).Length
            if ($size -lt 256) {
                throw "Descarga demasiado pequeña ($size bytes)."
            }
            return
        } catch {
            $lastError = $_
            Remove-Item -Force -LiteralPath $Destination -ErrorAction SilentlyContinue
        }
    }
    throw "No fue posible descargar $Label. Último error: $lastError"
}

function Verify-FullPackage {
    if (-not (Test-Path -LiteralPath $FullManifest -PathType Leaf)) {
        throw "Falta MANIFEST_FULL_SHA256.txt. Vuelve a extraer el ZIP completo."
    }

    $count = 0
    $covered = @{}
    foreach ($line in Get-Content -LiteralPath $FullManifest) {
        $value = [string]$line
        if ([string]::IsNullOrWhiteSpace($value)) { continue }
        if ($value -notmatch '^([0-9A-Fa-f]{64})  (.+)$') {
            throw "Línea inválida en MANIFEST_FULL_SHA256.txt: $value"
        }
        $expected = $Matches[1].ToLowerInvariant()
        $rel = $Matches[2].Replace('/', '\')
        if ([IO.Path]::IsPathRooted($rel) -or $rel -match '(^|[\\/])\.\.([\\/]|$)' -or $rel.Contains(':')) {
            throw "Ruta inválida en manifest: $rel"
        }
        $path = Join-Path $SourceDir $rel
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Archivo del paquete no encontrado: $rel"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "SHA-256 inválido: $rel"
        }
        $covered[$rel.ToLowerInvariant()] = $true
        $count++
    }
    foreach ($file in Get-ChildItem -LiteralPath $SourceDir -Recurse -File) {
        $relative = $file.FullName.Substring($SourceDir.Length + 1)
        if ($relative -like '__pycache__*' -or $relative -like '*.pyc') { continue }
        if ($relative -eq 'MANIFEST_FULL_SHA256.txt') { continue }
        if (-not $covered.ContainsKey($relative.ToLowerInvariant())) { throw "Archivo sin verificar: $relative" }
    }
    Write-Host "  [OK] Integridad del paquete: $count archivos." -ForegroundColor Green
}

function Install-PrivatePython {
    if ((Test-Path -LiteralPath $PythonExe -PathType Leaf) -and (Test-Path -LiteralPath $PythonwExe -PathType Leaf)) {
        try {
            & $PythonExe -c "import sys,struct; assert sys.version_info[:2] == (3,13); assert struct.calcsize('P')*8 == 64"
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] Runtime privado existente reutilizado." -ForegroundColor Green
                return
            }
        } catch {}
    }

    if (Test-Path -LiteralPath $PythonDir) {
        Remove-Item -Recurse -Force -LiteralPath $PythonDir
    }
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null

    $installed = $false
    foreach ($candidate in $PythonCandidates) {
        $version = [string]$candidate.Version
        $installer = Join-Path $TempRoot "python-$version-amd64.exe"
        try {
            Download-File -Urls @([string]$candidate.Url) -Destination $installer -Label "Python $version x64"
            $signature = Get-AuthenticodeSignature -LiteralPath $installer
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
                throw 'Firma del instalador de Python inválida o editor inesperado.'
            }
            $args = @(
                "/quiet",
                "InstallAllUsers=0",
                ('TargetDir="' + $PythonDir + '"'),
                "PrependPath=0",
                "AppendPath=0",
                "Include_launcher=0",
                "Include_test=0",
                "Include_doc=0",
                "Include_pip=1",
                "Include_tcltk=1",
                "Include_dev=0",
                "Shortcuts=0",
                "SimpleInstall=1"
            )
            $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
            if ($proc.ExitCode -ne 0) {
                throw "El instalador de Python terminó con código $($proc.ExitCode)."
            }
            if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
                throw "python.exe no apareció en el runtime privado."
            }
            Run-C $PythonExe -c "import sys,struct; assert sys.version_info[:2] == (3,13); assert struct.calcsize('P')*8 == 64"
            $installed = $true
            Write-Host "  [OK] Python privado $version instalado." -ForegroundColor Green
            break
        } catch {
            Write-Host "  [WARN] Python $version no pudo instalarse: $($_.Exception.Message)" -ForegroundColor Yellow
            if (Test-Path -LiteralPath $PythonDir) {
                Remove-Item -Recurse -Force -LiteralPath $PythonDir -ErrorAction SilentlyContinue
            }
        }
    }

    if (-not $installed) {
        throw "No fue posible instalar un Python x64 compatible. Verifica acceso HTTPS a python.org."
    }
}

function Copy-AppFiles {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $files = @('mobhector.pyw', 'transfer_engine.py', 'credential_store.py', 'host_key_store.py',
        'x11_forwarding.py', 'terminal_io.py', 'session_validation.py', 'remote_text.py', 'install_support.py', 'requirements.txt',
        'requirements-windows.lock', 'VERSION.txt', 'mobhector.bat', 'mobhector_debug.bat',
        'rusterfiles.bat', 'actualizar_mobhector.bat', 'actualizar_mobhector.ps1',
        'desinstalar_mobhector.bat', 'desinstalar_mobhector.ps1', 'MANIFEST_SHA256.txt')
    foreach ($name in $files) {
        Copy-Item -Force -LiteralPath (Join-Path $SourceDir $name) -Destination (Join-Path $InstallDir $name)
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'assets') | Out-Null
}

function Install-TerminalAssets {
    $X11Source = Join-Path $SourceDir 'vendor\vcxsrv'
    if (-not (Test-Path -LiteralPath (Join-Path $X11Source 'vcxsrv.exe'))) {
        throw 'Falta el servidor X11 integrado. Extrae el ZIP completo.'
    }
    $VendorDir = Join-Path $InstallDir 'vendor'
    New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null
    Copy-Item -Recurse -Force -LiteralPath $X11Source -Destination $VendorDir

    foreach ($name in @('xterm.js', 'xterm.css', 'xterm-addon-fit.js', 'terminal.html', 'LICENSE-xterm.txt', 'LICENSE-xterm-addon-fit.txt')) {
        Copy-Item -Force -LiteralPath (Join-Path $SourceDir "assets\$name") -Destination (Join-Path $InstallDir "assets\$name")
    }
}

function Add-UserPath {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $current) { $current = "" }
    $parts = @($current.Split(';') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $already = $false
    foreach ($part in $parts) {
        if ($part.TrimEnd('\') -ieq $InstallDir.TrimEnd('\')) {
            $already = $true
            break
        }
    }
    if (-not $already) {
        $newPath = (($parts + $InstallDir) -join ';')
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "  [OK] $InstallDir agregado al PATH del usuario." -ForegroundColor Green
    } else {
        Write-Host "  [OK] PATH del usuario ya contiene $InstallDir." -ForegroundColor Green
    }
    if (($env:Path -split ';') -notcontains $InstallDir) {
        $env:Path = "$InstallDir;$env:Path"
    }
}

function Create-Shortcuts {
    $shell = New-Object -ComObject WScript.Shell
    $launcher = Join-Path $InstallDir "mobhector.bat"

    $desktop = [Environment]::GetFolderPath("Desktop")
    if ($desktop) {
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "MobHector.lnk"))
        $shortcut.TargetPath = $launcher
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "MobHector $AppVersion - SSH/SFTP terminal"
        $shortcut.Save()
    }

    $programs = [Environment]::GetFolderPath("Programs")
    if ($programs) {
        $folder = Join-Path $programs "MobHector"
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $shortcut = $shell.CreateShortcut((Join-Path $folder "MobHector.lnk"))
        $shortcut.TargetPath = $launcher
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "MobHector $AppVersion - SSH/SFTP terminal"
        $shortcut.Save()
    }
    Write-Host "  [OK] Accesos directos creados." -ForegroundColor Green
}

function Validate-Install {
    Push-Location $InstallDir
    try {
    Run-C $PythonExe -m pip --version
    Run-C $PythonExe -c "import paramiko, PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; from PySide6.QtWebChannel import QWebChannel"
    Run-C $PythonExe -m py_compile `
        (Join-Path $InstallDir "mobhector.pyw") `
        (Join-Path $InstallDir "transfer_engine.py") `
        (Join-Path $InstallDir "credential_store.py") `
        (Join-Path $InstallDir "host_key_store.py")

    foreach ($asset in @("xterm.js", "xterm.css", "xterm-addon-fit.js", "terminal.html")) {
        $path = Join-Path $InstallDir "assets\$asset"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Asset terminal faltante después de instalación: $asset"
        }
    }

    Run-C $PythonExe -c "from pathlib import Path; from install_support import validate_runtime; validate_runtime(Path.cwd())"
    } finally { Pop-Location }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
try { Start-Transcript -Path $LogFile -Append | Out-Null } catch {}

try {
    Clear-Host
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "       MOBHECTOR $AppVersion - INSTALADOR COMPLETO PARA WINDOWS" -ForegroundColor White
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "Instalación privada por usuario. No requiere cambiar ExecutionPolicy." -ForegroundColor Gray
    Write-Host "No incluye sesiones, contraseñas, known_hosts ni datos de otro usuario." -ForegroundColor Gray
    Write-Host "Requiere conexión HTTPS durante la primera instalación." -ForegroundColor Gray

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "MobHector requiere Windows x64."
    }

    if (Test-Path -LiteralPath $InstalledApp -PathType Leaf) {
        throw "Ya existe MobHector en $InstallDir. Para actualizar usa un paquete UPDATE ONLY; este instalador completo es para una instalación nueva."
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    Step "[1/9] Verificando integridad del paquete..."
    Verify-FullPackage

    Step "[2/9] Preparando directorios..."
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    Write-Host "  [OK] Destino: $InstallDir" -ForegroundColor Green

    Step "[3/9] Instalando Python privado..."
    Install-PrivatePython

    Step "[4/9] Instalando dependencias verificables desde PyPI..."
    Run-C $PythonExe -m pip install --disable-pip-version-check --no-warn-script-location "--only-binary=:all:" --require-hashes -r (Join-Path $SourceDir "requirements-windows.lock")

    Step "[5/9] Copiando MobHector..."
    $FreshCopyStarted = $true
    Copy-AppFiles

    Step "[6/9] Instalando motor xterm.js local..."
    Install-TerminalAssets

    Step "[7/9] Configurando comandos y accesos directos..."
    Add-UserPath
    Create-Shortcuts

    Step "[8/9] Ejecutando QA de instalación..."
    Validate-Install
    Write-Host "  [OK] QA aprobado." -ForegroundColor Green

    Step "[9/9] Verificación final..."
    $versionFile = (Get-Content -LiteralPath (Join-Path $InstallDir "VERSION.txt") -Raw).Trim()
    if ($versionFile -ne $AppVersion) {
        throw "VERSION.txt no coincide: '$versionFile'"
    }
    $coreText = Get-Content -LiteralPath $InstalledApp -Raw
    if ($coreText -notmatch ('APP_VERSION\s*=\s*["'']' + [regex]::Escape($AppVersion) + '["'']')) {
        throw "El core instalado no reporta APP_VERSION $AppVersion."
    }
    Write-Host "  [OK] MobHector $AppVersion instalado correctamente." -ForegroundColor Green

    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host "            [OK] MOBHECTOR $AppVersion LISTO PARA USAR" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Puedes abrirlo desde el acceso directo o, en una consola NUEVA:" -ForegroundColor White
    Write-Host "  mobhector" -ForegroundColor Cyan
    Write-Host "  rusterfiles" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Datos de usuario: %APPDATA%\MobHector" -ForegroundColor Gray
    Write-Host "Credenciales: Windows Credential Manager" -ForegroundColor Gray
    Write-Host "Log instalación: $LogFile" -ForegroundColor Gray

} catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ($FreshCopyStarted -and (Test-Path -LiteralPath $InstalledApp)) {
        Remove-Item -Force -LiteralPath $InstalledApp
    }
    Write-Host "La instalación no fue aprobada. Puedes corregir la causa y ejecutar de nuevo." -ForegroundColor Red
    Write-Host "Log: $LogFile" -ForegroundColor Yellow
    exit 1
} finally {
    Remove-Item -Recurse -Force -LiteralPath $TempRoot -ErrorAction SilentlyContinue
    try { Stop-Transcript | Out-Null } catch {}
}

exit 0
