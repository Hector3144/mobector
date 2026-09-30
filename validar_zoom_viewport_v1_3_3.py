# -*- coding: utf-8 -*-
"""QA específico MobHector 1.3.4: zoom no debe crear historial fantasma."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parent
APP=(ROOT/'mobhector.pyw').read_text(encoding='utf-8-sig')
HTML=(ROOT/'assets'/'terminal.html').read_text(encoding='utf-8-sig')
UP=(ROOT/'actualizar_mobhector.ps1').read_text(encoding='utf-8-sig')
checks=[]
def add(n,c): checks.append((n,bool(c)))
try: ast.parse(APP); add('python_syntax',True)
except SyntaxError: add('python_syntax',False)
add('version_133','APP_VERSION = "1.4.1"' in APP)
add('capture_before_fontsize', HTML.find('zoomPinLiveEnd = isNormalBufferAtBottom();') < HTML.find('term.options.fontSize = BASE_FONT_SIZE'))
add('zoom_live_end_state','let zoomPinLiveEnd = false;' in HTML)
add('zoom_live_end_helper','function pinZoomToLiveEnd(generation)' in HTML)
add('zoom_scroll_bottom','term.scrollToBottom();' in HTML and 'pinZoomToLiveEnd(generation);' in HTML)
add('zoom_generation_guard','generation !== zoomFitGeneration' in HTML)
add('fit_live_end_branch','if (zoomPinLiveEnd) {' in HTML and 'fitAddon.fit();' in HTML)
add('history_branch_preserved','preserveHistoryViewportAfter(function ()' in HTML)
add('generic_fit_captures_bottom','let wasAtBottom = false;' in HTML and 'before.viewportY >= before.baseY' in HTML)
add('generic_fit_pins_bottom','const pinToLiveEnd = function ()' in HTML)
add('history_marker_only_when_needed','const marker = wasAtBottom ? null : captureHistoryMarker();' in HTML)
add('double_frame_kept', HTML.count('requestAnimationFrame(function ()') >= 2)
add('delayed_refit_kept','}, 90);' in HTML)
add('pty_resize_kept','bridge.resize(' in HTML and 'scheduleReportSize(0);' in HTML)
add('startup_access_kept','Ctrl+Shift+U' in APP and 'Startup Command' in APP)
add('zoom_plus_kept','self.zoom_in_button = QPushButton("+")' in APP)
add('zoom_minus_kept','self.zoom_out_button = QPushButton("−")' in APP)
failed=[]
for n,c in checks:
 print(f"[{'OK' if c else 'FAIL'}] {n}")
 if not c: failed.append(n)
if failed:
 print('FAILED:',', '.join(failed)); raise SystemExit(1)
print(f'ZOOM VIEWPORT 1.3.4 QA: OK ({len(checks)} checks)')
