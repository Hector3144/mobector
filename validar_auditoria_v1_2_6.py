# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "mobhector.pyw").read_text(encoding="utf-8-sig")
HTML = (ROOT / "assets" / "terminal.html").read_text(encoding="utf-8")
TRANSFER = (ROOT / "transfer_engine.py").read_text(encoding="utf-8")
TREE = ast.parse(APP)

checks = {}

checks["version_126"] = 'APP_VERSION = "1.5.0"' in APP
checks["module_doc_version"] = "MobHector v1.5.0" in APP

duplicates = []
module_defs = {}
for child in TREE.body:
    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        module_defs.setdefault(child.name, []).append(child.lineno)
for name, lines in module_defs.items():
    if len(lines) > 1:
        duplicates.append(("<module>", name, lines))

for node in TREE.body:
    if not isinstance(node, ast.ClassDef):
        continue
    names = {}
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.setdefault(child.name, []).append(child.lineno)
    for name, lines in names.items():
        if len(lines) > 1:
            duplicates.append((node.name, name, lines))

checks["no_duplicate_defs"] = not duplicates
checks["one_remote_join"] = APP.count("def remote_join(") == 1

# Config/session hardening.
checks["delete_last_session_stays_empty"] = (
    'self.config["sessions"].append(' not in APP[
        APP.find("def delete_session(self):"):
        APP.find("def session_context", APP.find("def delete_session(self):"))
    ]
)
checks["malformed_session_isolated"] = (
    "normalized_sessions = []" in APP
    and "if not isinstance(raw_session, dict):" in APP
)
checks["session_port_sanitized"] = "port = max(1, min(65535, port))" in APP

# SFTP/path safety.
checks["remote_name_validation"] = "def validate_remote_entry_name" in APP
checks["remote_join_child_safe"] = 'child = child.lstrip("/")' in APP
checks["app_sftp_enoent_classifier"] = (
    "def is_sftp_not_found" in APP
    and "if not is_sftp_not_found(exc):" in APP
)
checks["go_inbox_reuses_safe_mkdir"] = "ensure_remote_directory(sftp, inbox)" in APP
checks["refresh_stale_error_guard"] = "def _refresh_error_if_current" in APP
checks["refresh_skips_dot_entries"] = 'if a.filename in (".", ".."):' in APP

# Transfer hardening.
checks["transfer_enoent_classifier"] = (
    "def _is_not_found" in TRANSFER
    and "if _is_not_found(exc):" in TRANSFER
)
checks["transfer_path_traversal_guard"] = (
    "def _safe_child_name" in TRANSFER
    and "Nombre remoto no seguro" in TRANSFER
)
checks["transfer_permission_not_hidden"] = "if not _is_not_found(exc):" in TRANSFER

# Terminal lifecycle/performance.
checks["python_fit_debounce"] = (
    "self._fit_timer = QTimer(self)" in APP
    and "def schedule_fit_terminal" in APP
)
checks["reader_retirement"] = (
    "_RETIRED_TERMINAL_READERS = set()" in APP
    and "_release_retired_terminal_reader" in APP
)
checks["js_geometry_dedupe"] = (
    "lastReportedGeometry" in HTML
    and "geometry === lastReportedGeometry" in HTML
)
checks["js_resize_observer_debounce"] = (
    "ResizeObserver(function ()" in HTML
    and "scheduleFit(45)" in HTML
)
checks["no_direct_resize_observer_fit"] = (
    "const observer = new ResizeObserver(function () {\n        window.fitTerminal();" not in HTML
)

# History integrity.
checks["scrollback_500k_default"] = "scrollback: 500000" in HTML
checks["scrollback_1m_max"] = "Math.min(1000000" in HTML
checks["protect_scrollback_default"] = '"terminal_protect_scrollback": True' in APP
checks["ed3_protected"] = (
    "term.parser.registerCsiHandler" in HTML
    and "{final: 'J'}" in HTML
    and "ps === 3" in HTML
    and "protect_scrollback" in HTML
)
checks["ed2_kept"] = "scrollOnEraseInDisplay: true" in HTML
checks["no_term_clear_api"] = "window.term.clear()" not in APP
checks["visible_clear_keeps_history"] = (
    "window.mobhectorClearVisible" in HTML
    and "buildPreservingClearSequence()" in HTML
)
checks["marker_based_history_anchor"] = (
    "captureHistoryMarker" in HTML
    and "term.registerMarker(offset)" in HTML
    and "restoreHistoryMarker" in HTML
)
checks["no_absolute_history_anchor"] = "historyViewportLine" not in HTML
checks["history_badge_is_distance"] = (
    "líneas preservadas hasta el final" in HTML
    or "líneas hasta el final" in HTML
)

# MultiExec/selection regressions.
checks["multiexec_paste"] = (
    "paste_input = Signal(str)" in APP
    and "def handle_multi_exec_paste" in APP
)
checks["selection_autoscroll"] = "selectionAutoScrollTimer" in HTML

# Glass and terminal keyboard regressions.
checks["private_glass_only_when_needed"] = (
    "needs_private_glass" in APP
    and "and not app_is_glass" in APP
)
checks["vim_escape"] = (
    'QKeySequence("Ctrl+Shift+Esc")' in APP
    and r"\x1b" in HTML
)
checks["vim_mouse"] = "term.onBinary(function (data)" in HTML
checks["ctrlv_single_paste"] = (
    "lastPasteRequestAt" in HTML
    and "_last_paste_monotonic" in APP
)
checks["hostkey_security"] = "AutoAddPolicy" not in APP

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if duplicates:
    print("Duplicates:", duplicates)

if failed:
    print("\nAUDITORIA 1.2.6 FAIL:", ", ".join(failed))
    raise SystemExit(1)

print("\nAUDITORIA 1.2.6: OK")
