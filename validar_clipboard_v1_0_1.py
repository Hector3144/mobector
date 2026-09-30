# -*- coding: utf-8 -*-
from pathlib import Path
import ast, re, sys

root = Path(__file__).resolve().parent
app = (root / "mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root / "assets" / "terminal.html").read_text(encoding="utf-8")

ast.parse(app)

checks = {
    "mobhector_version_present": 'APP_VERSION = "1.4.0"' in app,
    "capture_keydown": bool(re.search(
        r"document\.addEventListener\(\s*['\"]keydown['\"]",
        html, re.S
    )),
    "capture_true": bool(re.search(
        r"document\.addEventListener\(\s*['\"]keydown['\"].*?\n\s*true\s*\)",
        html, re.S
    )),
    "prevent_default": "ev.preventDefault();" in html,
    "stop_propagation": "ev.stopPropagation();" in html,
    "stop_immediate": "ev.stopImmediatePropagation();" in html,
    "paste_residual_guard": bool(re.search(
        r"document\.addEventListener\(\s*['\"]paste['\"]",
        html, re.S
    )),
    "js_dedupe": "lastPasteRequestAt" in html and "< 45" in html,
    "py_dedupe": "_last_paste_monotonic" in app and "< 0.060" in app,
    "qt_clipboard": "QApplication.clipboard().text()" in app,
    "right_click": "terminalElement.addEventListener('contextmenu'" in html,
    "custom_handler_single_owner":
        "El pegado de teclado se procesa sólo en el handler DOM" in html,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")

if failed:
    print("\\nCLIPBOARD QA FAIL:", ", ".join(failed))
    sys.exit(1)

print("\\nCLIPBOARD QA: OK")
