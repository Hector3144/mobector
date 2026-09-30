# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys
root=Path(__file__).resolve().parent
app=(root/'mobhector.pyw').read_text(encoding='utf-8-sig')
html=(root/'assets'/'terminal.html').read_text(encoding='utf-8')
ast.parse(app)
checks={
 'version':'APP_VERSION = "1.5.0"' in app,
 'anchor':'function captureHeldClickAnchor(ev)' in html,
 'absolute_row':'buffer.viewportY + visibleRow' in html,
 'normal_only':'buffer !== term.buffer.normal' in html,
 'select_func':'function selectHeldClickToTerminalEnd()' in html,
 'logical_end':'buffer.baseY + buffer.cursorY' in html,
 'linear_length':'(endRow - startRow) * term.cols' in html,
 'xterm_select':'term.select(' in html,
 'scroll_bottom':'term.scrollToBottom();' in html,
 'end_guard':"key === 'end'" in html and 'pointerDownState.anchor' in html,
 'mouseup_restore':'restoreHeldClickEndSelection();' in html,
 'no_mass_autocopy':'No se autocopia' in html,
 'click_cursor':'maybePositionCursorFromClick(ev, downState)' in html,
 'autoscroll':'selectionAutoScrollTimer' in html,
 'history_keys':'window.mobhectorHistoryNavigate' in html,
 'clear_fix':'buildPreservingClearSequence()' in html,
 'vim_mouse':'term.onBinary(function (data)' in html,
 'vim_escape':'QKeySequence("Ctrl+Shift+Esc")' in app,
 'multiexec':'def handle_multi_exec_paste' in app,
 'glass':'self.terminal_backdrop = BackdropWidget()' in app,
 'hostkey':'AutoAddPolicy' not in app,
}
cols=100; sr=10; sc=20; er=30; ec=5
length=(er-sr)*cols+ec-sc
checks['math_model']=length==1985
failed=[]
for n,ok in checks.items():
 print(f"[{'OK' if ok else 'FAIL'}] {n}")
 if not ok: failed.append(n)
print(f'SELECTION MODEL: {sr}/{sc} -> {er}/{ec} = {length} cells')
if failed:
 print('\nLEFT-HOLD+END QA FAIL: '+', '.join(failed)); sys.exit(1)
print('\nLEFT-HOLD+END QA: OK')
