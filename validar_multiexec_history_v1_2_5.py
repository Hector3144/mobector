# -*- coding: utf-8 -*-
from pathlib import Path
import ast,sys
root=Path(__file__).resolve().parent
app=(root/'mobhector.pyw').read_text(encoding='utf-8-sig')
html=(root/'assets'/'terminal.html').read_text(encoding='utf-8')
ast.parse(app)
checks={
'version':'APP_VERSION = "1.5.0"' in app,
'default_500k':'"terminal_scrollback": 500000' in app,
'max_1m_py':'("terminal_scrollback", 5000, 1000000, 500000)' in app,
'max_1m_ui':'self.scrollback.setRange(5000, 1000000)' in app,
'max_1m_js':'Math.min(1000000' in html,
'migration':'terminal_history_v125_migrated' in app and 'old_scrollback == 30000' in app,
'sticky':'captureHistoryMarker' in html and 'historyViewportLocked' in html,
'badge':'id="historyBadge"' in html,
'history_keys':'term.scrollPages(' in html and 'term.scrollToTop()' in html and 'term.scrollToBottom()' in html,
'autoscroll':'selectionAutoScrollTimer' in html and 'term.scrollLines(delta)' in html and '_mobhectorAutoScroll' in html,
'paste_signal':'paste_input = Signal(str)' in app,
'paste_local_once':('self.send_raw(text, announce=False)' in app or 'self.send_raw(payload, announce=False)' in app),
'paste_emit':('self.paste_input.emit(text)' in app or 'self.paste_input.emit(terminal_text)' in app),
'paste_handler':'def handle_multi_exec_paste(self, source_tab, data):' in app,
'paste_status':'MultiExec: pegado enviado a' in app,
'ctrlv':'lastPasteRequestAt' in html and '_last_paste_monotonic' in app,
'vim_escape':'QKeySequence("Ctrl+Shift+Esc")' in app,
'vim_mouse':'term.onBinary(function (data)' in html,
'glass':'self.terminal_backdrop = BackdropWidget()' in app,
'hostkey':'AutoAddPolicy' not in app,
}
failed=[]
for k,v in checks.items():
 print(f"[{'OK' if v else 'FAIL'}] {k}")
 if not v: failed.append(k)
if failed:
 print('\nMULTIEXEC/HISTORY QA FAIL:',', '.join(failed));sys.exit(1)
print('\nMULTIEXEC/HISTORY QA: OK')
