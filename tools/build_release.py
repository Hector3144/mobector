"""Build a clean reproducible installer ZIP and integrity manifests."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','__pycache__','.pytest_cache','.ruff_cache','dist','MobHectorRuntime'}
FORBIDDEN={'config.json','known_hosts','.env','MANIFEST_SHA256.txt','MANIFEST_FULL_SHA256.txt'}

def build():
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    version=(ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?',version):
        raise ValueError('VERSION.txt must contain a valid release version')
    target=dist/f'MobHector_{version}_WINDOWS_INSTALL_UPDATE.zip' 
    with tempfile.TemporaryDirectory() as temp:
        stage=Path(temp)/f'MobHector_{version}';stage.mkdir()
        for path in sorted(ROOT.rglob('*')):
            rel=path.relative_to(ROOT)
            if not path.is_file() or any(p in SKIP for p in rel.parts):continue
            if path.name in FORBIDDEN or path.suffix in ('.pyc','.log','.zip','.bundle'):continue
            dst=stage/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dst)
        def manifest():
            return ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(stage).as_posix()+'\n'
                           for p in sorted(stage.rglob('*')) if p.is_file())
        (stage/'MANIFEST_SHA256.txt').write_text(manifest(),encoding='utf-8')
        (stage/'MANIFEST_FULL_SHA256.txt').write_text(manifest(),encoding='utf-8')
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    info=zipfile.ZipInfo(path.relative_to(Path(temp)).as_posix(),date_time=(2026,9,29,0,0,0))
                    info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100755 if path.suffix=='.sh' else 0o100644)<<16
                    z.writestr(info,path.read_bytes())
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n')
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity verification failed')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write(f'version={version}\nzip={target}\nchecksum={target.with_suffix(".zip.sha256")}\n')
    print(str(target));print(digest)
    return target
if __name__=='__main__':build()
