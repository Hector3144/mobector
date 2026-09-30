# -*- coding: utf-8 -*-
from pathlib import Path
import ast

root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root/"assets"/"terminal.html").read_text(encoding="utf-8")
ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.4.1"' in app,
    "terminal_backdrop": "self.terminal_backdrop = BackdropWidget()" in app,
    "private_glass": "needs_private_glass" in app,
    "glass_config": '"glass"' in app and "glass_darkness" in app,
    "live_all_terminals":
        "for w in self.all_terminal_tabs():" in app,
    "detached_sync":
        "self.session_widget.set_visual_mode(" in app,
    "webengine_transparent":
        "WA_TranslucentBackground" in app
        and "QColor(0, 0, 0, 0)" in app,
    "html_glass":
        'data-theme="glass"' in html
        and "background:transparent!important" in html,
    "vim_escape":
        'QKeySequence("Ctrl+Shift+Esc")' in app,
    "clipboard":
        "lastPasteRequestAt" in html,
    "vim_mouse":
        "term.onBinary(function (data)" in html,
    "security":
        "AutoAddPolicy" not in app,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"[{'OK' if v else 'FAIL'}] {k}")
if failed:
    print("\\nTERMINAL GLASS QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\\nTERMINAL GLASS QA: OK")
