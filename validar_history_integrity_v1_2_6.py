# -*- coding: utf-8 -*-
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
APP = (ROOT/"mobhector.pyw").read_text(encoding="utf-8-sig")
HTML = (ROOT/"assets"/"terminal.html").read_text(encoding="utf-8")
ast.parse(APP)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in APP,
    "default_500k": '"terminal_scrollback": 500000' in APP,
    "max_1m": '("terminal_scrollback", 5000, 1000000, 500000)' in APP,
    "protect_default": '"terminal_protect_scrollback": True' in APP,
    "protect_ui": "Proteger historial contra clear" in APP,
    "protect_runtime_py": '"protect_scrollback"' in APP,
    "protect_runtime_js": "terminalInteractionPrefs.protect_scrollback" in HTML,
    "ed3_parser_hook": "registerCsiHandler" in HTML and "ps === 3" in HTML,
    "ed3_consumed": "return true;" in HTML,
    "ed2_preserved": "scrollOnEraseInDisplay: true" in HTML,
    "clear_api_removed": "window.term.clear()" not in APP,
    "visual_clear_ed2": (
        "mobhectorClearVisible" in HTML
        and "buildPreservingClearSequence()" in HTML
    ),
    "marker_capture": "captureHistoryMarker" in HTML,
    "marker_register": "term.registerMarker(offset)" in HTML,
    "marker_restore": "restoreHistoryMarker(marker)" in HTML,
    "absolute_anchor_removed": "historyViewportLine" not in HTML,
    "output_uses_marker": "const marker = captureHistoryMarker();" in HTML,
    "fit_uses_marker": "preserveHistoryViewportAfter(function ()" in HTML,
    "badge_clear_wording": (
        "líneas preservadas hasta el final" in HTML
        or "líneas hasta el final" in HTML
    ),
    "resize_dedup": "lastReportedGeometry" in HTML,
    "resize_debounce": "scheduleFit(45)" in HTML,
}
failed=[]
for n, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {n}")
    if not ok: failed.append(n)
if failed:
    print("\nHISTORY INTEGRITY QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\nHISTORY INTEGRITY QA: OK")
