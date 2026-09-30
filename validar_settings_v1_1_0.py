# -*- coding: utf-8 -*-
from pathlib import Path
import ast, re, sys

root = Path(__file__).resolve().parent
app = (root / "mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root / "assets" / "terminal.html").read_text(encoding="utf-8")

ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.1"' in app,
    "general_dialog": "class GeneralSettingsDialog(QDialog):" in app,
    "appearance_expanded": '"midnight", "graphite", "forest", "purple", "sepia"' in app,
    "accent": '"accent_color": "cyan"' in app,
    "density": '"ui_density": "normal"' in app,
    "terminal_font": '"terminal_font_family": "Cascadia Mono"' in app,
    "terminal_cursor": '"terminal_cursor_style": "block"' in app,
    "terminal_scrollback": '"terminal_scrollback": 500000' in app,
    "terminal_runtime_apply": "def set_terminal_preferences(self, preferences):" in app,
    "ssh_keepalive": '"ssh_keepalive": 20' in app,
    "ssh_timeouts": '"ssh_connect_timeout": 12' in app and '"ssh_auth_timeout": 15' in app,
    "worker_threads": '"worker_threads": 8' in app,
    "confirm_close": '"confirm_close_session": True' in app,
    "settings_menu": '"Preferencias generales…"' in app,
    "config_folder": "def open_config_folder(self):" in app,
    "log_folder": "def open_log_folder(self):" in app,
    "reset_preserves_sessions": "Las sesiones guardadas" in app,
    "terminal_themes": all(
        name in html for name in (
            "midnight:{", "forest:{", "purple:{", "sepia:{"
        )
    ),
    "terminal_preferences_js": "window.setTerminalPreferences" in html,
    "ctrlv_fix_preserved": "lastPasteRequestAt" in html and "_last_paste_monotonic" in app,
}

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("\\nSETTINGS QA FAIL:", ", ".join(failed))
    sys.exit(1)

print("\\nSETTINGS QA: OK")
