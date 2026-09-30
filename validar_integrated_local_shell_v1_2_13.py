# -*- coding: utf-8 -*-
from pathlib import Path
import ast

root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root/"assets"/"terminal.html").read_text(encoding="utf-8")
ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.5.0"' in app,
    "conpty": "class LocalConPTYChannel:" in app
        and "CreatePseudoConsole" in app
        and "ResizePseudoConsole" in app,
    "local_connection": "class LocalShellConnection(QObject):" in app,
    "same_terminal": "class LocalShellTerminal(QWidget):" in app
        and "self.terminal = TerminalWidget(" in app,
    "no_external_window":
        'shutil.which("wt.exe")' not in app[
            app.find("def open_local_shell"):
            app.find("def build_sftp_dock")
        ]
        and "subprocess.Popen(" not in app[
            app.find("def open_local_shell"):
            app.find("def build_sftp_dock")
        ],
    "button": 'self.local_shell_button.setText(">_ Local")' in app,
    "powershell_cmd": '"PowerShell"' in app and '"CMD"' in app,
    "shortcut": 'QKeySequence("Ctrl+Shift+L")' in app,
    "appearance": "for w in self.all_terminal_tabs():" in app,
    "preferences": "for tab in self.all_terminal_tabs():" in app,
    "history": "buildPreservingClearSequence()" in html,
    "vim_paste": "bracketedPasteMode" in html,
    "portable_hresult": "wintypes.HRESULT" not in app,
    "security": "AutoAddPolicy" not in app,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"[{'OK' if v else 'FAIL'}] {k}")
if failed:
    print("\\nINTEGRATED LOCAL SHELL QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\\nINTEGRATED LOCAL SHELL QA: OK")
