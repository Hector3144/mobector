# -*- coding: utf-8 -*-
"""QA focalizado: pestañas SSH/Local desacopladas no deben desaparecer."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
APP = (ROOT / 'mobhector.pyw').read_text(encoding='utf-8-sig')
checks = []

def check(name, cond):
    checks.append((name, bool(cond)))
    print(f"[{'OK' if cond else 'FAIL'}] {name}")

try:
    ast.parse(APP)
    check('python_syntax', True)
except Exception:
    check('python_syntax', False)

check('version_134', 'APP_VERSION = "1.4.0"' in APP)
check('detached_window_class', 'class DetachedSessionWindow(QMainWindow):' in APP)
DETACHED = APP.split('class DetachedSessionWindow(QMainWindow):',1)[1].split('class ToolbarCustomizeDialog',1)[0]
check('detached_toolbar_no_main_context_handler', 'customContextMenuRequested.connect(self.show_toolbar_context_menu)' not in DETACHED)
check('detached_toolbar_movable', 'tb.setMovable(True)' in APP)
check('detach_transaction_try', 'try:\n            window = DetachedSessionWindow(tab, title, self)' in APP)
check('detach_restores_tab_on_error', 'self.tabs.insertTab(restore_index, tab, title)' in APP)
check('detach_rollback_reactivate', '"detach-rollback"' in APP)
check('detach_error_visible', 'La pestaña fue "\n                "restaurada automáticamente' in APP)
check('detach_registry_cleanup', 'self.detached_windows.pop(tab, None)' in APP)
check('ssh_and_local_supported', '(SessionTerminal, LocalShellTerminal)' in APP)
check('reattach_preserved', 'def reattach_detached_session(self, tab, title):' in APP)
check('close_detached_preserved', 'def close_detached_session(self, tab, title):' in APP)

failed = [name for name, ok in checks if not ok]
if failed:
    print('DETACH FIX QA: FAILED:', ', '.join(failed))
    raise SystemExit(1)
print(f'DETACH FIX QA: OK ({len(checks)} checks)')
