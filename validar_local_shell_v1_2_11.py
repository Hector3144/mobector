# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys
root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
ast.parse(app)
checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "launcher": "def open_local_shell" in app,
    "powershell": '"PowerShell"' in app,
    "cmd": '"CMD"' in app,
    "integrated_conpty": "class LocalConPTYChannel:" in app,
    "integrated_tab": "class LocalShellTerminal(QWidget):" in app,
    "no_external_wt": 'shutil.which("wt.exe")' not in app,
    "no_saved_ssh_session": 'self.config["sessions"].append' not in app[
        app.find("def open_local_shell"):app.find("def build_sftp_dock")
    ],
    "security": "AutoAddPolicy" not in app,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"[{'OK' if v else 'FAIL'}] {k}")
if failed:
    print("\nLOCAL SHELL REGRESSION QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\nLOCAL SHELL REGRESSION QA: OK")
