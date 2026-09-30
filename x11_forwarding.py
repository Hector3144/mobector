"""Authenticated SSH X11 forwarding. No remote cookie is a local X credential."""
import hmac
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time

PROTOCOL = b'MIT-MAGIC-COOKIE-1'


def parse_display(value):
    match = re.fullmatch(r'(?:localhost|127\.0\.0\.1|unix)?:(\d{1,4})(?:\.(\d{1,3}))?', value)
    if not match or int(match[1]) > 999:
        raise ValueError('Display X11 local inválido. Usa :0 o localhost:10.0.')
    return int(match[1]), int(match[2] or 0), value.startswith((':', 'unix:'))


def read_cookie(path, number):
    with Path(path).expanduser().open('rb') as f:
        data = f.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('Archivo Xauthority demasiado grande')
    pos = 0
    local_names = {socket.gethostname().encode(), socket.getfqdn().encode(), b'localhost', b''}
    while pos < len(data):
        if pos + 2 > len(data): raise ValueError('Xauthority truncado')
        family = struct.unpack_from('!H', data, pos)[0]; pos += 2
        fields = []
        for _ in range(4):
            if pos + 2 > len(data): raise ValueError('Xauthority truncado')
            size = struct.unpack_from('!H', data, pos)[0]; pos += 2
            if pos + size > len(data): raise ValueError('Xauthority truncado')
            fields.append(data[pos:pos+size]); pos += size
        address, display, protocol, cookie = fields
        local = (family == 65535 or family == 256 and address in local_names or
                 family == 0 and address == socket.inet_aton('127.0.0.1') or
                 family == 6 and address == b'\0' * 15 + b'\1')
        if local and display == str(number).encode() and protocol == PROTOCOL and len(cookie) == 16:
            return cookie
    raise ValueError('No hay una cookie MIT-MAGIC-COOKIE-1 local para ese display en Xauthority.')


def write_authority(path, number, cookie):
    fields = (b'', str(number).encode(), PROTOCOL, cookie)
    payload = struct.pack('!H', 65535) + b''.join(struct.pack('!H', len(x))+x for x in fields)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(payload)


def read_exact(stream, count, deadline):
    data = bytearray()
    while len(data) < count:
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('Timeout X11')
        stream.settimeout(remaining)
        part = stream.recv(count-len(data))
        if not part: raise EOFError('Conexión X11 incompleta')
        data.extend(part)
    return bytes(data)


def read_setup(stream):
    deadline = time.monotonic()+5
    header = read_exact(stream, 12, deadline)
    if header[0] not in (ord('l'), ord('B')): raise ValueError('Orden de bytes X11 inválido')
    order = '<' if header[0] == ord('l') else '>'
    major, minor, name_len, cookie_len = struct.unpack_from(order+'HHHH', header, 2)
    if major != 11 or minor != 0 or name_len != len(PROTOCOL) or cookie_len != 16:
        raise ValueError('Autenticación X11 inválida')
    body = read_exact(stream, ((name_len+3)//4)*4+((cookie_len+3)//4)*4, deadline)
    if body[:name_len] != PROTOCOL: raise ValueError('Protocolo X11 no permitido')
    return header, body, ((name_len+3)//4)*4


class LocalDisplay:
    def __init__(self, session):
        self.process = None
        self.directory = None
        try:
            if session.get('x11_mode', 'managed' if os.name == 'nt' else 'existing') == 'managed':
                self._start_windows(session)
            else:
                value = session.get('x11_display') or os.environ.get('DISPLAY', '')
                self.number, self.screen, self.unix = parse_display(value)
                authority = session.get('x11_authority') or os.environ.get('XAUTHORITY') or str(Path.home()/'.Xauthority')
                self.cookie = read_cookie(authority, self.number)
            # Fail before opening the remote shell if the local display is unreachable.
            probe = self.connect(); probe.close()
        except Exception:
            self.close()
            raise

    def _start_windows(self, session):
        if os.name != 'nt': raise ValueError('VcXsrv automático sólo está disponible en Windows.')
        configured = session.get('x11_executable', '')
        candidates = [configured] if configured else [str(Path(os.environ.get(k, 'C:/Program Files'))/'VcXsrv/vcxsrv.exe') for k in ('ProgramFiles', 'ProgramFiles(x86)')]
        executable = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
        if executable is None or executable.name.lower() != 'vcxsrv.exe':
            raise ValueError('Instala VcXsrv y selecciona vcxsrv.exe en Editar sesión → X11. Consulta docs/X11.md.')
        self.number = None
        for number in range(60, 100):
            with socket.socket() as probe:
                try: probe.bind(('127.0.0.1', 6000+number))
                except OSError: continue
                self.number = number; break
        if self.number is None: raise OSError('No hay un display X11 libre entre 60 y 99.')
        self.screen, self.unix = 0, False
        self.cookie = secrets.token_bytes(16)
        self.directory = tempfile.mkdtemp(prefix='mobhector-x11-')
        authority = str(Path(self.directory)/'authority')
        write_authority(authority, self.number, self.cookie)
        # Never use -ac or modify firewall policy. -auth keeps access control enabled.
        self.process = subprocess.Popen([str(executable), ':'+str(self.number), '-multiwindow',
            '-nowgl', '-listen', 'tcp', '-auth', authority], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            if self.process.poll() is not None: raise RuntimeError('VcXsrv terminó durante el arranque.')
            try:
                probe = self.connect(); probe.close(); return
            except OSError: time.sleep(.1)
        raise TimeoutError('VcXsrv no está disponible tras 10 segundos.')

    def connect(self):
        if self.unix and os.name != 'nt':
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); sock.settimeout(5)
            try: sock.connect('/tmp/.X11-unix/X'+str(self.number))
            except Exception: sock.close(); raise
            return sock
        return socket.create_connection(('127.0.0.1', 6000+self.number), timeout=5)

    def close(self):
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try: self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=3)
            finally: self.process = None
        if self.directory:
            shutil.rmtree(self.directory, ignore_errors=True); self.directory = None
        self.cookie = b''


class X11Forwarder:
    def __init__(self, session, report=lambda text: None):
        self.display = LocalDisplay(session)
        self.report = report
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.slots = threading.BoundedSemaphore(16)
        self.cookies = {}
        self.streams = set()

    def request(self, shell):
        fake = secrets.token_bytes(16)
        with self.lock:
            self.cookies = {k:v for k,v in self.cookies.items() if not v.closed}
            if len(self.cookies) >= 32: raise RuntimeError('Demasiadas terminales X11 en la conexión')
            self.cookies[fake] = shell
        try:
            shell.request_x11(screen_number=self.display.screen, auth_protocol=PROTOCOL.decode(),
                auth_cookie=fake.hex(), single_connection=False, handler=self.accept)
        except Exception:
            with self.lock: self.cookies.pop(fake, None)
            raise RuntimeError('El servidor rechazó X11. Revisa X11Forwarding y xauth en el servidor SSH.') from None

    def accept(self, channel, source):
        # Paramiko invokes this on its transport thread: no socket I/O here.
        with self.lock:
            if self.stopped.is_set() or not self.slots.acquire(blocking=False):
                channel.close(); return
            self.streams.add(channel)
        threading.Thread(target=self._forward, args=(channel,), daemon=True).start()

    def _forward(self, channel):
        local = None
        done = threading.Event()
        def pump(source, target):
            try:
                while not done.is_set() and not self.stopped.is_set():
                    try: data = source.recv(65536)
                    except socket.timeout: continue
                    if not data: break
                    target.sendall(data)
            except (OSError, EOFError): pass
            finally:
                done.set()
                channel.close()
                if local is not None: local.close()
        try:
            header, body, offset = read_setup(channel)
            fake = body[offset:offset+16]
            with self.lock:
                valid = any(hmac.compare_digest(fake,k) and not shell.closed for k,shell in self.cookies.items())
                if self.stopped.is_set() or not valid: raise ValueError('Cookie X11 rechazada')
            local = self.display.connect()
            with self.lock:
                if self.stopped.is_set(): raise EOFError()
                self.streams.add(local)
            local.sendall(header+body[:offset]+self.display.cookie+body[offset+16:])
            channel.settimeout(1); local.settimeout(1)
            other = threading.Thread(target=pump, args=(local,channel), daemon=True); other.start()
            pump(channel,local)
            other.join(timeout=2)
        except Exception:
            if not self.stopped.is_set(): self.report('X11: conexión gráfica rechazada o interrumpida. Revisa servidor X y autenticación.')
        finally:
            done.set(); channel.close()
            if local is not None: local.close()
            with self.lock:
                self.streams.discard(channel); self.streams.discard(local)
            self.slots.release()

    def close(self):
        with self.lock:
            self.stopped.set(); self.cookies.clear()
            for stream in list(self.streams):
                try: stream.close()
                except OSError: pass
        self.display.close()
