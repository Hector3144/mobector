# -*- coding: utf-8 -*-
from pathlib import Path
import ast
root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
ast.parse(app)
button = app.find('self.local_shell_button.setText(">_ Local")')
session_list = app.find("self.session_list = QListWidget()")
checks = {
    "version": 'APP_VERSION = "1.4.0"' in app,
    "sessions_button": button > 0,
    "button_below_session_list": button > session_list,
    "dropdown": "MenuButtonPopup" in app,
    "powershell": '"PowerShell"' in app,
    "cmd": '"CMD"' in app,
    "shortcut": 'QKeySequence("Ctrl+Shift+L")' in app,
    "integrated": "LocalConPTYChannel" in app,
    "no_external_terminal": 'shutil.which("wt.exe")' not in app,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"[{'OK' if v else 'FAIL'}] {k}")
if failed:
    print("\nLOCAL SHELL UI REGRESSION QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\nLOCAL SHELL UI REGRESSION QA: OK")
