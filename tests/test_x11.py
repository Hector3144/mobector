import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import paramiko
import x11_forwarding as x


def packet(cookie, order='<'):
    return (bytes([ord('l') if order=='<' else ord('B'),0])+struct.pack(order+'HHHHH',11,0,len(x.PROTOCOL),len(cookie),0)
            +x.PROTOCOL+b'\0'*((-len(x.PROTOCOL))%4)+cookie)


class Display:
    cookie=b'L'*16
    screen=0
    def __init__(self,*args):self.connections=[];self.closed=False
    def connect(self):
        a,b=socket.socketpair();b.settimeout(3);self.connections.append(b);return a
    def close(self):self.closed=True


class X11Tests(unittest.TestCase):
    def test_display_is_local_only(self):
        self.assertEqual(x.parse_display('localhost:10.0'),(10,0,False))
        self.assertEqual(x.parse_display(':0'),(0,0,True))
        for value in ('evil:0','192.0.2.1:0',':1000',':0;cmd','localhost:-1'):
            with self.assertRaises(ValueError):x.parse_display(value)

    def test_authority_and_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'auth';x.write_authority(p,61,b'A'*16)
            self.assertEqual(x.read_cookie(p,61),b'A'*16)
            with self.assertRaises(ValueError):x.read_cookie(p,62)
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaises(ValueError):x.read_cookie(p,61)

    def test_setup_endianness(self):
        for order in ('<','>'):
            a,b=socket.socketpair()
            try:
                a.sendall(packet(b'F'*16,order))
                header,body,offset=x.read_setup(b)
                self.assertEqual(body[offset:offset+16],b'F'*16)
                self.assertEqual(len(header),12)
            finally:a.close();b.close()

    def test_oversize_header_rejected_before_reading_body(self):
        a,b=socket.socketpair()
        try:
            a.sendall(b'l\0'+struct.pack('<HHHHH',11,0,65535,65535,0))
            with self.assertRaises(ValueError):x.read_setup(b)
        finally:a.close();b.close()

    def test_bad_cookie_never_opens_local_display(self):
        with patch.object(x,'LocalDisplay',Display):f=x.X11Forwarder({})
        a,b=socket.socketpair()
        try:
            f.accept(b,('untrusted',1));a.sendall(packet(b'X'*16));a.settimeout(2)
            self.assertEqual(a.recv(1),b'')
            self.assertEqual(f.display.connections,[])
        finally:a.close();f.close()

    def test_closed_terminal_cookie_rejected(self):
        class Shell:
            closed=True
        with patch.object(x,'LocalDisplay',Display):f=x.X11Forwarder({})
        f.cookies[b'F'*16]=Shell()
        a,b=socket.socketpair()
        try:
            f.accept(b,('local',1));a.sendall(packet(b'F'*16));a.settimeout(2)
            self.assertEqual(a.recv(1),b'')
            self.assertEqual(f.display.connections,[])
        finally:a.close();f.close()

    def test_import_does_not_enable_x11(self):
        from session_validation import validate_session
        s=validate_session(dict(host='example.com',username='test',x11_enabled=True,x11_executable='bad.exe'))
        self.assertIs(s['x11_enabled'],False);self.assertNotIn('x11_executable',s)

    def test_real_ssh_x11_request_cookie_swap_and_data(self):
        class Server(paramiko.ServerInterface):
            def check_auth_password(self,u,p):return paramiko.AUTH_SUCCESSFUL
            def get_allowed_auths(self,u):return 'password'
            def check_channel_request(self,kind,chanid):return paramiko.OPEN_SUCCEEDED
            def check_channel_x11_request(self,channel,single,protocol,cookie,screen):
                self.cookie=cookie;return True
        a,b=socket.socketpair();server=Server()
        st=paramiko.Transport(a);st.add_server_key(paramiko.RSAKey.generate(2048))
        started=threading.Event();st.start_server(event=started,server=server)
        ct=paramiko.Transport(b);ct.connect(username='test',password='test',hostkey=st.get_server_key())
        shell=ct.open_session(timeout=3);remote=st.accept(3)
        with patch.object(x,'LocalDisplay',Display):f=x.X11Forwarder({})
        xc=None
        try:
            f.request(shell)
            self.assertNotEqual(bytes.fromhex(server.cookie.decode() if isinstance(server.cookie,bytes) else server.cookie),f.display.cookie)
            xc=st.open_x11_channel(('127.0.0.1',4321));xc.settimeout(3)
            fake=bytes.fromhex(server.cookie.decode() if isinstance(server.cookie,bytes) else server.cookie)
            setup=packet(fake)
            for chunk in (setup[:3],setup[3:11],setup[11:]):xc.sendall(chunk)
            deadline=time.monotonic()+3
            while not f.display.connections and time.monotonic()<deadline:time.sleep(.01)
            local=f.display.connections[0]
            received=x.read_exact(local,len(setup),time.monotonic()+3)
            self.assertEqual(received,packet(f.display.cookie))
            xc.sendall(b'client-data');self.assertEqual(local.recv(11),b'client-data')
            local.sendall(b'server-data');self.assertEqual(xc.recv(11),b'server-data')
            f.close();self.assertEqual(local.recv(1),b'');local.close()
        finally:
            f.close()
            if xc:xc.close()
            shell.close();remote.close();ct.close();st.close()

if __name__=='__main__':unittest.main()
