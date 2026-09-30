# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys

root = Path(__file__).resolve().parent
app = (root / "mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root / "assets" / "terminal.html").read_text(encoding="utf-8")

ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "click_setting": '"terminal_click_to_cursor": True' in app,
    "middle_paste_setting": '"terminal_middle_click_paste": False' in app,
    "bell_setting": '"terminal_bell_style": "none"' in app,
    "scrollbar_setting": '"terminal_show_scrollbar": True' in app,
    "tab_position_setting": '"tab_position": "top"' in app,
    "detach_setting": '"detach_distance": 70' in app,
    "ssh_compression": '"ssh_compression": False' in app,
    "auto_reconnect": '"auto_reconnect": False' in app,
    "sftp_hidden": '"sftp_show_hidden_default": True' in app,
    "bridge_local_input": "def localInput(self, data: str):" in app,
    "local_not_multiexec": "self.send_raw(data, announce=False)" in app,
    "normal_buffer_guard": "buffer.active === buffer.normal" in html,
    "bottom_guard": "buffer.active.viewportY === buffer.active.baseY" in html,
    "same_row_guard": "if (row !== currentRow)" in html,
    "click_arrow_left": "cursorSequence('left')" in html,
    "click_arrow_right": "cursorSequence('right')" in html,
    "drag_guard": "movement > 6 || term.hasSelection()" in html,
    "middle_paste": "terminalInteractionPrefs.middle_click_paste" in html,
    "bell_runtime": "term.options.bellStyle" in html,
    "word_runtime": "term.options.wordSeparator" in html,
    "scrollbar_runtime": "data-scrollbar" in html,
    "auto_reconnect_timer": "_auto_reconnect_timer" in app,
    "compression_runtime": '"compress": bool(' in app,
    "tab_runtime": "self.tabs.setTabPosition(" in app,
    "detach_runtime": "self.main_tab_bar.DETACH_VERTICAL_MARGIN" in app,
    "multiexec_confirm": '"Confirmar MultiExec"' in app,
    "ctrlv_hotfix": "lastPasteRequestAt" in html and "_last_paste_monotonic" in app,
    "hostkey_security": "AutoAddPolicy" not in app,
}

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("\\nADVANCED SETTINGS QA FAIL:", ", ".join(failed))
    sys.exit(1)

print("\\nADVANCED SETTINGS QA: OK")
