# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys

root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root/"assets"/"terminal.html").read_text(encoding="utf-8")
ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "module_version": "MobHector v1.5.0" in app,
    "qt_webview": "class TerminalWebView(QWebEngineView):" in app,
    "signal": "history_shortcut = Signal(str)" in app,
    "pageup": "Qt.Key.Key_PageUp" in app,
    "pagedown": "Qt.Key.Key_PageDown" in app,
    "home": "Qt.Key.Key_Home" in app,
    "end": "Qt.Key.Key_End" in app,
    "press_intercept": "def keyPressEvent(self, event):" in app,
    "release_intercept": "def keyReleaseEvent(self, event):" in app,
    "specialized_view": "self.view = TerminalWebView(self)" in app,
    "qt_local_handler": "def _handle_history_shortcut" in app,
    "js_history_api": "window.mobhectorHistoryNavigate" in html,
    "xterm_barrier":
        "(key === 'pageup' || key === 'pagedown')" in html,
    "dom_barrier":
        "ev.preventDefault()" in html
        and "window.mobhectorHistoryNavigate(" in html,
    "clear_preserve":
        "buildPreservingClearSequence()" in html,
    "markers":
        "term.registerMarker(offset)" in html,
    "no_explicit_esc5_send":
        "bridge.input('\\x1b[5~')" not in html
        and 'bridge.input("\\x1b[5~")' not in html,
    "vim_escape":
        'QKeySequence("Ctrl+Shift+Esc")' in app,
    "hostkey":
        "AutoAddPolicy" not in app,
}

failed=[]
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("\\nHISTORY KEYS QA FAIL:", ", ".join(failed))
    raise SystemExit(1)

print("\\nHISTORY KEYS QA: OK")
