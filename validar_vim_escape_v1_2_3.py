# -*- coding: utf-8 -*-
from pathlib import Path
import ast, re, sys
root = Path(__file__).resolve().parent
app = (root / 'mobhector.pyw').read_text(encoding='utf-8-sig')
html = (root / 'assets' / 'terminal.html').read_text(encoding='utf-8')
ast.parse(app)
checks = {
    'version_123': 'APP_VERSION = "1.4.1"' in app,
    'no_plain_esc_application_shortcut': 'QShortcut(QKeySequence("Esc"), self)' not in app,
    'no_shortcut_escape_member': 'self.shortcut_escape =' not in app,
    'immersive_ctrl_shift_esc': 'QKeySequence("Ctrl+Shift+Esc")' in app,
    'dom_escape_capture': "key === 'escape'" in html and "bridge.input('\\x1b')" in html,
    'escape_prevent_default': 'ev.preventDefault();' in html,
    'escape_stop_propagation': 'ev.stopPropagation();' in html,
    'escape_return_after_send': "bridge.input('\\x1b');" in html and "term.focus();" in html and "return;" in html,
    'colon_not_special_cased': "key === ':'" not in html and 'key === ":"' not in html,
    'ctrlv_single_paste': 'lastPasteRequestAt' in html and '_last_paste_monotonic' in app,
    'vim_mouse_preserved': 'term.onBinary(function (data)' in html and 'terminal_tui_native_mouse' in app,
    'hostkey_security': 'AutoAddPolicy' not in app,
}
failed=[]
for name,ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok: failed.append(name)
if failed:
    print('\nVIM ESC/WQ QA FAIL:', ', '.join(failed)); sys.exit(1)
print('\nVIM ESC/WQ QA: OK')
