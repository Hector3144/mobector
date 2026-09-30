# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys
root=Path(__file__).resolve().parent
app=(root/'mobhector.pyw').read_text(encoding='utf-8-sig')
html=(root/'assets'/'terminal.html').read_text(encoding='utf-8')
ast.parse(app)
checks={
 'version':'APP_VERSION = "1.5.0"' in app,
 'clean_special_copy':'function getCleanHeldClickEndSelectionText()' in html,
 'buffer_reader':'buffer.getLine(row)' in html,
 'trim_padding':'line.translateToString(true, fromColumn, toColumn)' in html,
 'wrapped_lines':'!line.isWrapped' in html,
 'saved_end':'endRow: endRow' in html and 'endColumn: endColumn' in html,
 'normal_fallback':'text = term.getSelection();' in html,
 'bracketed_detect':'term.modes.bracketedPasteMode' in html,
 'bool_slot':'@Slot(bool)' in app and 'def pasteClipboard(self, bracketed: bool = False):' in app,
 'bp_start':'"\\x1b[200~"' in app,
 'bp_end':'"\\x1b[201~"' in app,
 'newline_norm':'.replace("\\n", "\\r")' in app,
 'multiexec_clean':'self.paste_input.emit(terminal_text)' in app,
 'toolbar_js':'window.pasteTerminalClipboard' in app,
 'dedupe':'lastPasteRequestAt' in html and '_last_paste_monotonic' in app,
 'left_end':'selectHeldClickToTerminalEnd' in html,
 'clear':'buildPreservingClearSequence()' in html,
 'history':'window.mobhectorHistoryNavigate' in html,
 'vim_escape':'QKeySequence("Ctrl+Shift+Esc")' in app,
 'vim_mouse':'term.onBinary(function (data)' in html,
 'hostkey':'AutoAddPolicy' not in app,
}
failed=[]
for k,v in checks.items():
 print(f"[{'OK' if v else 'FAIL'}] {k}")
 if not v: failed.append(k)
if failed:
 print('FAIL:',','.join(failed)); sys.exit(1)
print('VIM COPY/PASTE QA: OK')
