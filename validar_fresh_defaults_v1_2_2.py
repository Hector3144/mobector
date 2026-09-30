# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys

root = Path(__file__).resolve().parent
app = (root / "mobhector.pyw").read_text(encoding="utf-8-sig")
ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "zero_sessions": '"sessions": []' in app,
    "blank_name": '"name": ""' in app,
    "blank_host": '"host": ""' in app,
    "blank_username": '"username": ""' in app,
    "port_22": '"port": 22' in app,
    "auto_home": '"remote_home": ""' in app,
    "auto_inbox": '"remote_inbox": ""' in app,
    "empty_sessions_valid":
        "Cero sesiones es un estado válido" in app,
    "normalize_login_home":
        'sftp.normalize(configured_home or ".")' in app,
    "default_inbox_under_home":
        '"archivos_enviados"' in app
        and "remote_join(" in app,
    "mkdir_p":
        "def ensure_remote_directory(sftp, path: str):" in app,
    "auto_create":
        "ensure_remote_directory(sftp, inbox)" in app,
    "resolve_during_connect":
        "resolve_remote_home_and_inbox(" in app,
    "resolved_home_runtime":
        '"_resolved_remote_home"' in app,
    "resolved_inbox_runtime":
        '"_resolved_remote_inbox"' in app,
    "browser_effective_home":
        "def effective_home(self):" in app,
    "browser_effective_inbox":
        "def effective_inbox(self):" in app,
    "port_dialog":
        'self.port.setValue(int(s.get("port", 22) or 22))' in app,
    "runtime_sanitized":
        '"_resolved_remote_home", "_resolved_remote_inbox"' in app,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")

if failed:
    print("\\nFRESH DEFAULTS QA FAIL:", ", ".join(failed))
    sys.exit(1)

print("\\nFRESH DEFAULTS QA: OK")
