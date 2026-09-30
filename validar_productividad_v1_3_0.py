# -*- coding: utf-8 -*-
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
app = (ROOT / "mobhector.pyw").read_text(encoding="utf-8-sig")
html = (ROOT / "assets" / "terminal.html").read_text(encoding="utf-8-sig")

checks = {
    "version_130": 'APP_VERSION = "1.4.0"' in app,
    "quick_connect": "class QuickConnectDialog" in app and "def quick_connect" in app,
    "quick_commands": '"quick_commands": [' in app and "build_quick_commands_dock" in app,
    "startup_command": "startup_command" in app and "_run_startup_command" in app,
    "terminal_search": "mobhectorSearchTerminal" in html and "search_current_terminal" in app,
    "transcript": "start_transcript" in app and 'LOG_DIR / "Sessions"' in app,
    "safe_export": "export_sessions_safe" in app and 'result.pop("credential_id", None)' in app,
    "safe_import": "import_sessions_safe" in app and 'session["remember_password"] = False' in app,
    "no_new_daemon_bind": "0.0.0.0" not in app,
    "credential_store_preserved": "credential_write_password" in app and "credential_read_password" in app,
    "known_hosts_preserved": "configure_host_key_client" in app and "KNOWN_HOSTS_FILE" in app,
}

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
print("PRODUCTIVITY 1.3.1 QA: OK")
