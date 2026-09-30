# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys

root = Path(__file__).resolve().parent
app = (root / "mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root / "assets" / "terminal.html").read_text(encoding="utf-8")

ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "native_default": '"terminal_tui_native_mouse": True' in app,
    "fallback_default": '"terminal_tui_arrow_fallback": True' in app,
    "native_ui": "Permitir mouse nativo en Vim / TUI" in app,
    "fallback_ui": "Fallback Vim/TUI" in app,
    "binary_slot": "def binaryInput(self, data: str):" in app,
    "binary_raw": "bytes((ord(char) & 0xFF)" in app,
    "onBinary": "term.onBinary(function (data)" in html,
    "mouse_report_local": "looksLikeMouseReport" in html and "bridge.localInput(data)" in html,
    "mouse_tracking": "term.modes.mouseTrackingMode" in html,
    "native_guard": "hasNativeMouseTracking()" in html,
    "alternate_fallback": "isAlternateBuffer()" in html and "tui_arrow_fallback" in html,
    "app_cursor_keys": "term.modes.applicationCursorKeysMode" in html,
    "vertical_arrows": "cursorSequence('up')" in html and "cursorSequence('down')" in html,
    "horizontal_arrows": "cursorSequence('left')" in html and "cursorSequence('right')" in html,
    "cmdline_guard": "currentRow >= (term.rows - 1)" in html,
    "selection_guard": "movement > 6 || term.hasSelection()" in html,
    "shell_same_row": "if (row !== currentRow)" in html,
    "ctrlv_fix": "lastPasteRequestAt" in html and "_last_paste_monotonic" in app,
    "hostkey_safe": "AutoAddPolicy" not in app,
}

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("\\nVIM/TUI MOUSE QA FAIL:", ", ".join(failed))
    sys.exit(1)

print("\\nVIM/TUI MOUSE QA: OK")
