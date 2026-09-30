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

conn=Connection();conn.ch.payload=b''
terminal=m.TerminalWidget(conn);window.tabs.addTab(terminal,'Moba clasico');window.tabs.setCurrentWidget(terminal);terminal.start()
failures=[]
def js(code,callback=None):terminal.view.page().runJavaScript(code,callback or (lambda value:None))
def begin():
 js("window.setTerminalTheme('moba');window.term.reset();window.term.write('OK active running\\r\\nERROR failed denied\\r\\nwarning timeout\\r\\n192.0.2.10 /var/log/messages\\r\\n\\x1b[35mERROR\\x1b[0m color ANSI preservado\\r\\n');")
 m.QTimer.singleShot(800,check)
def check():
 js("JSON.stringify({state:window.getMobaHighlightState(),text:window.term.buffer.active.getLine(0).translateToString(true),ansi:window.term.buffer.active.getLine(4).getCell(0).getFgColor()})", inspected)
def inspected(value):
 import json
 v=json.loads(value);print('HIGHLIGHTS',v,flush=True)
 if v['state']['count']!=10 or v['text']!='OK active running' or v['ansi']!=5:failures.append(v)
 window.grab().save(str(Path(tempfile.gettempdir())/'mobhector-colors.png'))
 js("window.term.write('\\x1b[?1049hERROR 192.0.2.10');")
 m.QTimer.singleShot(500,alternate)
def alternate():
 js("JSON.stringify(window.getMobaHighlightState())",altchecked)
def altchecked(value):
 import json
 if json.loads(value)['count']!=0:failures.append('Alternate screen decorated')
 js("window.term.write('\\x1b[?1049l');window.setTerminalTheme('moba_plain');")
 m.QTimer.singleShot(500,plain)
def plain():js("JSON.stringify(window.getMobaHighlightState())",done)
def done(value):
 import json
 if json.loads(value)['count']!=0:failures.append('Plain theme decorated')
 terminal.close_terminal();window.close();print('COLOR_QA', failures or 'PASS',flush=True);app.exit(1 if failures else 0)
m.QTimer.singleShot(3000,begin)
m.QTimer.singleShot(15000,lambda:app.exit(2))
sys.exit(app.exec())
