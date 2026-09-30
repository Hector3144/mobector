"""Verified, rollback-capable application update; never writes user configuration."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime

REQUIRED = {'mobhector.pyw', 'transfer_engine.py', 'host_key_store.py',
            'credential_store.py', 'terminal_io.py', 'session_validation.py', 'remote_text.py',
            'assets/terminal.html', 'assets/xterm.js', 'assets/xterm.css',
            'assets/xterm-addon-fit.js', 'VERSION.txt', 'mobhector.bat', 'requirements.txt',
            'install_support.py'}
INSTALL_NAMES = REQUIRED | {
    'requirements-windows.lock', 'mobhector_debug.bat', 'rusterfiles.bat',
    'actualizar_mobhector.ps1', 'actualizar_mobhector.bat',
    'desinstalar_mobhector.ps1', 'desinstalar_mobhector.bat',
    'assets/LICENSE-xterm.txt', 'assets/LICENSE-xterm-addon-fit.txt',
}

PROTECTED = {'config.json', 'known_hosts', 'id_rsa', 'id_ed25519'}


def verify_package(source):
    source = Path(source).resolve()
    entries = []
    seen = set()
    for line in (source / 'MANIFEST_SHA256.txt').read_text(encoding='utf-8').splitlines():
        digest, separator, relative = line.partition('  ')
        rel = PurePosixPath(relative)
        if (not separator or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
                or not relative or '\\' in relative or ':' in relative or rel.is_absolute()
                or any(p in ('..', '.') for p in relative.split('/'))
                or relative.casefold() in seen or rel.name.casefold() in PROTECTED):
            raise ValueError('Manifest inválido: ruta, hash o entrada repetida')
        path = source.joinpath(*rel.parts)
        if not path.resolve().is_relative_to(source) or path.is_symlink():
            raise ValueError('Ruta del paquete fuera del origen')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Archivo ausente o modificado: {relative}')
        seen.add(relative.casefold())
        entries.append(relative)
    if not REQUIRED <= set(entries):
        raise ValueError('Paquete incompleto: faltan componentes obligatorios')
    return entries


def apply_update(source, destination, backup_root, validate=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Extrae el ZIP en una carpeta distinta a la instalación')
    entries = [rel for rel in verify_package(source) if rel in INSTALL_NAMES] + ["MANIFEST_SHA256.txt"]
    destination.mkdir(parents=True, exist_ok=True)
    backup = Path(backup_root) / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    previous = []
    # Complete backup before first write. Reject symlinks/junction escapes.
    for rel in entries:
        dst = destination / rel
        if not dst.resolve().is_relative_to(destination) or dst.is_symlink():
            raise ValueError(f'Destino inseguro: {rel}')
        if dst.exists():
            if not dst.is_file():
                raise ValueError(f'Destino no es un archivo: {rel}')
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
            previous.append(rel)
    (backup / 'rollback.json').write_text(json.dumps({'destination': str(destination),
        'entries': entries, 'previous': previous}, indent=2), encoding='utf-8')
    applied = []
    try:
        for rel in entries:
            dst = destination / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.mobhector-', dir=dst.parent)
            os.close(fd)
            try:
                shutil.copyfile(source / rel, temp)
                os.replace(temp, dst)
                applied.append(rel)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        for rel in entries:
            if hashlib.sha256((source / rel).read_bytes()).digest() != hashlib.sha256((destination / rel).read_bytes()).digest():
                raise ValueError(f"Verificación de copia falló: {rel}")
        if validate:
            validate(destination)
    except Exception as error:
        rollback_errors = []
        for rel in reversed(applied):
            try:
                if rel in previous:
                    shutil.copy2(backup / rel, destination / rel)
                else:
                    (destination / rel).unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(f'{rel}: {rollback_error}')
        if rollback_errors:
            raise RuntimeError(f'Rollback incompleto; respaldo en {backup}: {rollback_errors}') from error
        raise RuntimeError(f'Actualización revertida. Respaldo: {backup}. Causa: {error}') from error
    return backup


def validate_runtime(destination):
    subprocess.run([sys.executable, '-c',
        'import paramiko, PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; '
        'import terminal_io, session_validation, remote_text, transfer_engine, host_key_store, credential_store'],
        cwd=destination, check=True)
    for path in destination.glob('*.py*'):
        if path.suffix in ('.py', '.pyw'):
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify':
        print(f'Integridad: {len(verify_package(sys.argv[2]))} archivos correctos')
    elif len(sys.argv) == 4:
        result = apply_update(*sys.argv[1:], validate=validate_runtime)
        print(f'Actualización completada. Respaldo: {result}')
    else:
        raise SystemExit('Uso: install_support.py ORIGEN DESTINO BACKUPS | --verify ORIGEN')
