"""Real Paramiko SSH/SFTP loopback, ephemeral port, temporary test key/files."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import paramiko
from transfer_engine import upload, download

class Auth(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username,password)==('qa','temporary') else paramiko.AUTH_FAILED
    def get_allowed_auths(self, username): return 'password'
    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

class Files(paramiko.SFTPServerInterface):
    def __init__(self,server,*args,root,**kwargs): super().__init__(server,*args,**kwargs);self.root=Path(root)
    def p(self,path):
        target=(self.root/path.lstrip('/')).resolve()
        if not target.is_relative_to(self.root): raise PermissionError(path)
        return target
    def stat(self,path):
        try:return paramiko.SFTPAttributes.from_stat(self.p(path).stat())
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    lstat=stat
    def list_folder(self,path):
        result=[]
        for p in self.p(path).iterdir():
            a=paramiko.SFTPAttributes.from_stat(p.stat());a.filename=p.name;result.append(a)
        return result
    def open(self,path,flags,attr):
        try:
            fd=os.open(self.p(path), flags, 0o600)
            mode='r+b' if flags & os.O_RDWR else ('wb' if flags & os.O_WRONLY else 'rb')
            f=os.fdopen(fd,mode);h=paramiko.SFTPHandle(flags)
            h.readfile=f;h.writefile=f;return h
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def mkdir(self,path,attr):
        try:self.p(path).mkdir();return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def remove(self,path):
        try:self.p(path).unlink();return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def rename(self,src,dst):
        try:self.p(src).rename(self.p(dst));return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def posix_rename(self,src,dst):return self.rename(src,dst)

class RealSFTPTests(unittest.TestCase):
    def test_real_roundtrip_and_dedicated_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);remote=root/'remote';remote.mkdir();local=root/'local';local.mkdir();dest=root/'download'
            original=os.urandom(2*1024*1024+37);(local/'data.bin').write_bytes(original);(local/'empty').touch()
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
            key=paramiko.RSAKey.generate(2048);transports=[];stop=threading.Event()
            def server():
                try:
                    client,_=listener.accept();transport=paramiko.Transport(client);transports.append(transport)
                    transport.add_server_key(key);transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files,root=str(remote))
                    transport.start_server(server=Auth());stop.wait(20)
                finally:
                    for t in transports:t.close()
            thread=threading.Thread(target=server,daemon=True);thread.start()
            client=paramiko.SSHClient();port=listener.getsockname()[1]
            client.get_host_keys().add(f'[127.0.0.1]:{port}',key.get_name(),key)
            try:
                client.connect('127.0.0.1',port=port,username='qa',password='temporary',look_for_keys=False,allow_agent=False,timeout=5)
                browser=client.open_sftp()
                class Conn:
                    def ensure(self):pass
                    def open_sftp_session(self):return client.open_sftp()
                events=[]
                upload(Conn(),[str(local/'data.bin'),str(local/'empty')],'/files',events.append)
                self.assertEqual(events[-1]['percent'],100)
                self.assertEqual(browser.stat('/files/data.bin').st_size,len(original))
                download(Conn(),[{'path':'/files'}],str(dest),events.append)
                self.assertEqual((dest/'files/data.bin').read_bytes(),original)
                self.assertEqual((dest/'files/empty').read_bytes(),b'')
                self.assertFalse(browser.get_channel().closed)
                browser.close()
            finally:
                client.close();stop.set();listener.close();thread.join(5)
