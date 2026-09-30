"""Qt/WebEngine smoke test using a fake PTY. No remote host is contacted."""
import os
import sys
import tempfile
import importlib.machinery
import importlib.util
from pathlib import Path
import threading
import socket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='mobhector-smoke-')
os.environ['LOCALAPPDATA'] = os.environ['APPDATA']
loader=importlib.machinery.SourceFileLoader('mobhector_app',str(ROOT/'mobhector.pyw'))
spec=importlib.util.spec_from_loader('mobhector_app',loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class Channel:
    closed = False
    def __init__(self):
        self.payload = (('QA Unicode ñ 🚀 '+('x'*80)+'\r\n')*18000).encode()
        self.offset=0
        self.received=[]
        self.lock=threading.Lock()
    def recv(self,size):
        if self.closed: return b''
        if self.offset>=len(self.payload):
            threading.Event().wait(.05)
            raise socket.timeout()
        result=self.payload[self.offset:self.offset+size];self.offset+=len(result);return result
    def recv_ready(self):return self.offset<len(self.payload)
    def sendall(self,data):self.received.append(data)
    def resize_pty(self,**kwargs): pass
    def close(self):self.closed=True

class Connection:
    session={}
    def __init__(self):self.ch=Channel()
    def open_shell(self,**kwargs):return self.ch
    def get_transport(self):return None

app=m.QApplication([])
m._GUI_DISPATCHER=m.GuiDispatcher()
app.setStyle('Fusion');app.setPalette(m.palette_for_mode('dark'));app.setStyleSheet(m.QSS)
m.QSettings.setDefaultFormat(m.QSettings.Format.IniFormat)
m.QSettings.setPath(m.QSettings.Format.IniFormat,m.QSettings.Scope.UserScope,os.environ['APPDATA'])
window=m.MainWindow();window.showNormal();window.resize(1400,900)
conn=Connection()
# Build a real terminal widget with fake SSH transport.
terminal=m.TerminalWidget(conn)
window.tabs.addTab(terminal,'QA · 18.000 líneas');window.tabs.setCurrentWidget(terminal)
terminal.start()
failures=[]
def record_exception(kind, value, tb):
    failures.append(f'{kind.__name__}: {value}')
sys.excepthook=record_exception

def inspect():
    terminal.view.page().runJavaScript("JSON.stringify({ready:typeof window.fitTerminal==='function', text:document.body.innerText})", check)

def check(value):
    if not terminal.bridge._ready: failures.append('QWebChannel not ready')
    if conn.ch.offset!=len(conn.ch.payload): failures.append(f'Undrained output {conn.ch.offset}/{len(conn.ch.payload)}')
    if terminal.reader and terminal.reader._inflight!=0: failures.append(f'Missing xterm ACK {terminal.reader._inflight}')
    reader = terminal.reader
    channel = terminal.channel
    for cycle in range(3):
        detached = m.QDialog(window)
        layout = m.QVBoxLayout(detached)
        window.tabs.removeTab(window.tabs.indexOf(terminal))
        layout.addWidget(terminal)
        detached.show()
        terminal.reactivate_after_reparent('qa-detach', focus=False)
        app.processEvents()
        window.tabs.addTab(terminal, 'QA · terminal restaurada')
        window.tabs.setCurrentWidget(terminal)
        terminal.reactivate_after_reparent('qa-reattach', focus=False)
        detached.close()
        if terminal.reader is not reader or terminal.channel is not channel:
            failures.append('Reparent replaced connection')
    terminal.bridge.send_raw('echo QA\r')
    m.QTimer.singleShot(1800, verify_restored)

def verify_restored():
    terminal.view.page().runJavaScript("window.term && window.term.buffer.active.getLine(window.term.buffer.active.baseY).translateToString()", restored)

def restored(text):
    if not text or 'QA Unicode' not in text:
        failures.append('Terminal buffer lost after reparent')
    finish()

def finish():
    if b'echo QA\r' not in conn.ch.received:failures.append('Keyboard not delivered')
    output=Path(os.environ.get('MOBHECTOR_SMOKE_SCREENSHOT',str(Path(tempfile.gettempdir())/'mobhector-smoke.png')))
    window.grab().save(str(output))
    terminal.close_terminal();window.close()
    print('GUI_SMOKE', 'FAIL '+repr(failures) if failures else 'PASS: Qt startup, xterm, 18000 lines, UTF-8, ACK, keyboard, 3 reparent cycles, shutdown',flush=True)
    app.exit(1 if failures else 0)

m.QTimer.singleShot(12000,inspect)
sys.exit(app.exec())
