"""Prepare the Windows X server from a pinned upstream installer (build time only)."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

VERSION = '21.1.16.1'
URL = 'https://github.com/marchaesen/vcxsrv/releases/download/21.1.16.1/vcxsrv-64.21.1.16.1.installer.noadmin.exe'
SHA256 = 'dea6c7d67d3d15b4ed45c87b63a83c88f4aceaaef5425630f0e97a0bad70d620'
ROOT = Path(__file__).resolve().parents[1]


def bundle(stage):
    seven = os.environ.get('MOBHECTOR_7ZIP') or shutil.which('7zz') or shutil.which('7z')
    if not seven:
        raise RuntimeError('Install 7-Zip on the build machine to prepare the bundled X11 server.')
    with tempfile.TemporaryDirectory() as temp:
        installer = Path(temp) / 'vcxsrv.exe'
        cached = os.environ.get('MOBHECTOR_VCXSRV_INSTALLER')
        if cached:
            shutil.copyfile(cached, installer)
        else:
            with urllib.request.urlopen(URL, timeout=120) as response, installer.open('wb') as out:
                shutil.copyfileobj(response, out)
        if hashlib.sha256(installer.read_bytes()).hexdigest() != SHA256:
            raise ValueError('VcXsrv installer hash mismatch')
        dest = stage / 'vendor' / 'vcxsrv'
        dest.mkdir(parents=True)
        subprocess.run([seven, 'x', '-y', '-o'+str(dest), str(installer)], check=True,
                       stdout=subprocess.DEVNULL)
        for name in ('$PLUGINSDIR', 'uninstall.exe'):
            path = dest / name
            if path.is_dir(): shutil.rmtree(path)
            elif path.exists(): path.unlink()
        for name in ('vcxsrv.exe', 'xkbcomp.exe', 'vcruntime140.dll', 'msvcp140.dll'):
            if not (dest / name).is_file():
                raise RuntimeError('Incomplete VcXsrv runtime: '+name)
        shutil.copyfile(ROOT / 'docs' / 'LICENSE-VcXsrv.txt', dest / 'COPYING.txt')
        shutil.copyfile(ROOT / 'docs' / 'THIRD_PARTY_X11.md', dest / 'SOURCE_AND_NOTICES.md')
