# -*- coding: utf-8 -*-
from __future__ import annotations
import os, tempfile, shutil, threading
from pathlib import Path
from types import SimpleNamespace
from transfer_engine import upload, download

class LocalRemoteFile:
    def __init__(self, path, mode): self.f=open(path, "xb" if mode == "wx" else mode)
    def read(self,n=-1): return self.f.read(n)
    def write(self,data): return self.f.write(data)
    def flush(self): return self.f.flush()
    def close(self): return self.f.close()
    def set_pipelined(self, enabled): return None

class FakeSFTP:
    def __init__(self, root, owner=None):
        self.root=Path(root); self.owner=owner; self.closed=False
    def _p(self,remote): return self.root/remote.lstrip('/')
    def _attr(self,p,name=None):
        st=os.lstat(p)
        return SimpleNamespace(filename=name or Path(p).name,st_mode=st.st_mode,st_size=st.st_size,st_mtime=st.st_mtime,st_uid=getattr(st,'st_uid',0),st_gid=getattr(st,'st_gid',0))
    def stat(self,remote): return self._attr(self._p(remote))
    def lstat(self,remote): return self._attr(self._p(remote))
    def mkdir(self,remote): self._p(remote).mkdir()
    def open(self,remote,mode):
        p=self._p(remote); p.parent.mkdir(parents=True,exist_ok=True)
        return LocalRemoteFile(p,mode)
    def listdir_attr(self,remote):
        p=self._p(remote)
        return [self._attr(x,x.name) for x in sorted(p.iterdir())]
    def remove(self,remote): self._p(remote).unlink()
    def rename(self,src,dst): os.replace(self._p(src),self._p(dst))
    def posix_rename(self,src,dst): os.replace(self._p(src),self._p(dst))
    def close(self):
        self.closed=True
        if self.owner is not None: self.owner.closed_channels += 1

class FailingFile:
    def __init__(self, base, fail_write=False, fail_read=False):
        self.base=base; self.fail_write=fail_write; self.fail_read=fail_read; self.calls=0
    def read(self,n=-1):
        self.calls += 1
        if self.fail_read and self.calls >= 2:
            raise IOError('Fallo de lectura inyectado QA')
        return self.base.read(n)
    def write(self,data):
        self.calls += 1
        if self.fail_write and self.calls >= 2:
            raise IOError('Fallo de escritura inyectado QA')
        return self.base.write(data)
    def flush(self): return self.base.flush()
    def close(self): return self.base.close()
    def set_pipelined(self,enabled): return None

class FailingSFTP(FakeSFTP):
    def __init__(self, root, owner=None, fail_write=False, fail_read=False):
        super().__init__(root,owner)
        self.fail_write=fail_write; self.fail_read=fail_read
    def open(self,remote,mode):
        base=super().open(remote,mode)
        return FailingFile(
            base,
            fail_write=self.fail_write and 'w' in mode,
            fail_read=self.fail_read and 'r' in mode,
        )

class FailingConn:
    def __init__(self,root,fail_write=False,fail_read=False):
        self.root=Path(root); self.fail_write=fail_write; self.fail_read=fail_read
        self.sftp=FakeSFTP(root); self.lock=threading.RLock()
        self.opened_channels=0; self.closed_channels=0
    def ensure(self): return True
    def open_sftp_session(self):
        self.opened_channels += 1
        return FailingSFTP(
            self.root,self,
            fail_write=self.fail_write,
            fail_read=self.fail_read,
        )

class Conn:
    def __init__(self,root):
        self.root=Path(root)
        self.sftp=FakeSFTP(root)
        self.lock=threading.RLock()
        self.opened_channels=0
        self.closed_channels=0
    def ensure(self): return True
    def open_sftp_session(self):
        self.opened_channels += 1
        return FakeSFTP(self.root,self)

def assert_progress(events):
    assert events,'No hubo eventos de progreso'
    transferring=[e for e in events if e.get('stage')=='transferring']
    complete=[e for e in events if e.get('stage')=='complete']
    assert transferring,'No hubo eventos transferring'
    assert complete,'No hubo evento complete'
    assert int(complete[-1].get('percent',0))==100,complete[-1]
    assert int(complete[-1].get('bytes_done',-1))==int(complete[-1].get('bytes_total',-2)),complete[-1]
    assert all(int(e.get('percent',0))<=99 for e in transferring),transferring[-5:]
    assert events[-1].get('stage')=='complete',events[-3:]

def no_parts(root):
    leftovers=[p for p in Path(root).rglob('*mobhector-part-*')]
    assert not leftovers,f'Temporales sin limpiar: {leftovers}'

def main():
    tmp=Path(tempfile.mkdtemp(prefix='mobhector_transfer_test_'))
    try:
        local=tmp/'local'; remote=tmp/'remote'; dl=tmp/'downloads'
        local.mkdir(); remote.mkdir(); dl.mkdir()
        (local/'inventory.ini').write_bytes(b'x'*1434)
        (local/'empty.txt').write_bytes(b'')
        (local/'big.bin').write_bytes(os.urandom(1024*1024+333))
        (local/'espacio y ñ.txt').write_text('áéíóú ñ QA',encoding='utf-8')
        nested=local/'folder'/'sub'; nested.mkdir(parents=True)
        (nested/'a.txt').write_text('hola'*1000,encoding='utf-8')
        (nested/'b.bin').write_bytes(os.urandom(333333))

        conn=Conn(remote)
        events=[]
        r=upload(conn,[str(local/'inventory.ini')],'/home/test',events.append)
        assert (remote/'home/test/inventory.ini').read_bytes()==(local/'inventory.ini').read_bytes()
        assert r['bytes']==1434; assert_progress(events); no_parts(remote)

        # Reemplazo de destino existente debe publicar el nuevo archivo completo.
        (local/'inventory.ini').write_bytes(b'y'*2500)
        events=[]
        upload(conn,[str(local/'inventory.ini')],'/home/test',events.append)
        assert (remote/'home/test/inventory.ini').read_bytes()==b'y'*2500
        assert_progress(events); no_parts(remote)

        events=[]
        upload(conn,[str(local/'empty.txt'),str(local/'big.bin'),str(local/'folder')],'/home/test',events.append)
        assert (remote/'home/test/big.bin').read_bytes()==(local/'big.bin').read_bytes()
        assert (remote/'home/test/folder/sub/a.txt').read_bytes()==(nested/'a.txt').read_bytes()
        assert_progress(events); no_parts(remote)

        # Nombres con espacios/Unicode deben conservarse extremo a extremo.
        events=[]
        upload(conn,[str(local/'espacio y ñ.txt')],'/home/test',events.append)
        assert (remote/'home/test/espacio y ñ.txt').read_text(encoding='utf-8')=='áéíóú ñ QA'
        assert_progress(events); no_parts(remote)

        # Seguridad: un archivo nunca debe reemplazar/ocultar un directorio remoto.
        collision_dir = remote/'home/test/collision.txt'
        collision_dir.mkdir(parents=True, exist_ok=True)
        (collision_dir/'important.txt').write_text('NO TOCAR', encoding='utf-8')
        collision_src = local/'collision.txt'
        collision_src.write_text('archivo', encoding='utf-8')
        try:
            upload(conn,[str(collision_src)],'/home/test',lambda _e: None)
            raise AssertionError('Se esperaba IsADirectoryError por colisión archivo/directorio')
        except IsADirectoryError:
            pass
        assert collision_dir.is_dir()
        assert (collision_dir/'important.txt').read_text(encoding='utf-8') == 'NO TOCAR'
        no_parts(remote)

        # Fallo durante upload: el destino anterior no se toca y el .part se limpia.
        protected=remote/'home/test/protected.bin'
        protected.write_bytes(b'ORIGINAL')
        source=local/'protected.bin'; source.write_bytes(os.urandom(1024*1024+17))
        failing=FailingConn(remote,fail_write=True)
        try:
            upload(failing,[str(source)],'/home/test',lambda _e: None,chunk_size=256*1024)
            raise AssertionError('Se esperaba fallo de upload inyectado')
        except IOError:
            pass
        assert protected.read_bytes()==b'ORIGINAL'
        no_parts(remote)

        # Descargar a destino ya existente: os.replace sólo lo publica al final.
        (dl/'inventory.ini').write_bytes(b'old')
        events=[]
        rows=[{'path':'/home/test/inventory.ini','type':'f','size':2500}]
        r=download(conn,rows,str(dl),events.append)
        assert (dl/'inventory.ini').read_bytes()==b'y'*2500
        assert r['bytes']==2500; assert_progress(events); no_parts(dl)

        events=[]
        rows=[{'path':'/home/test/folder','type':'d','size':0},{'path':'/home/test/big.bin','type':'f','size':1024*1024+333}]
        download(conn,rows,str(dl),events.append)
        assert (dl/'folder/sub/b.bin').read_bytes()==(nested/'b.bin').read_bytes()
        assert (dl/'big.bin').read_bytes()==(local/'big.bin').read_bytes()
        assert_progress(events); no_parts(dl)

        # Fallo durante download: el archivo final anterior debe conservarse.
        source_remote=remote/'home/test/fail-download.bin'
        source_remote.write_bytes(os.urandom(1024*1024+99))
        final_local=dl/'fail-download.bin'; final_local.write_bytes(b'LOCAL-ORIGINAL')
        failing_dl=FailingConn(remote,fail_read=True)
        try:
            download(
                failing_dl,
                [{'path':'/home/test/fail-download.bin','type':'f','size':source_remote.stat().st_size}],
                str(dl),
                lambda _e: None,
                chunk_size=256*1024,
            )
            raise AssertionError('Se esperaba fallo de download inyectado')
        except IOError:
            pass
        assert final_local.read_bytes()==b'LOCAL-ORIGINAL'
        no_parts(dl)

        assert conn.opened_channels >= 6,conn.opened_channels
        assert conn.closed_channels == conn.opened_channels,(conn.opened_channels,conn.closed_channels)

        print('OK: motor de transferencias MobHector')
        print('OK: progreso final 100% sólo tras publicar destino')
        print('OK: canal SFTP dedicado por transferencia')
        print('OK: temporales .part se limpian')
        print('OK: reemplazo local/remoto validado')
        print('OK: archivo vacío, grande, Unicode/espacios y carpeta recursiva')
        print('OK: colisión archivo/directorio remoto bloqueada sin pérdida de datos')
        print('OK: fallos inyectados conservan destino anterior y limpian temporales')
        return 0
    finally:
        shutil.rmtree(tmp,ignore_errors=True)

if __name__=='__main__': raise SystemExit(main())
