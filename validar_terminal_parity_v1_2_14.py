# -*- coding: utf-8 -*-
from pathlib import Path
import ast

root = Path(__file__).resolve().parent
app = (root/"mobhector.pyw").read_text(encoding="utf-8-sig")
html = (root/"assets"/"terminal.html").read_text(encoding="utf-8")
tree = ast.parse(app)

checks = {
    "version": 'APP_VERSION = "1.4.0"' in app,
    "one_current_terminal_def":
        app.count("def current_terminal_tab(self):") == 1,
    "terminal_collection":
        "def attached_terminal_entries(self):" in app
        and "def all_terminal_tabs(self):" in app,
    "ssh_local_collection":
        "(SessionTerminal, LocalShellTerminal)" in app[
            app.find("def attached_terminal_entries"):
            app.find("def attached_session_entries")
        ],
    "multiexec_generic":
        "entries = self.attached_terminal_entries()" in app,
    "local_input_wired":
        "handle_multi_exec_input(source, data)" in app[
            app.find("def open_local_shell"):
            app.find("def close_local_shell_widget")
        ],
    "local_paste_wired":
        "handle_multi_exec_paste(source, data)" in app[
            app.find("def open_local_shell"):
            app.find("def close_local_shell_widget")
        ],
    "target_bracketed_paste":
        "def send_multi_exec_paste(self, data: str):" in app
        and "term.modes.bracketedPasteMode" in app,
    "paste_uses_target":
        "target.terminal.send_multi_exec_paste(data)" in app[
            app.find("def handle_multi_exec_paste"):
            app.find("def tab_context_menu")
        ],
    "local_ctrl_r":
        "tab.restart_shell()" in app[
            app.find("def reconnect_current"):
            app.find("def reconnect_session_tab")
        ],
    "local_context_detach":
        "Desacoplar en nueva ventana" in app[
            app.find("def tab_context_menu"):
            app.find("def show_detach_preview")
        ],
    "drag_detach_local":
        "(SessionTerminal, LocalShellTerminal)" in app[
            app.find("def detach_tab_by_drag"):
            app.find("def _position_detached_window")
        ],
    "direct_detach_local":
        "(SessionTerminal, LocalShellTerminal)" in app[
            app.find("def detach_tab(self"):
            app.find("def reattach_detached_session")
        ],
    "detached_local_restart":
        "Reiniciar Local Shell" in app[
            app.find("class DetachedSessionWindow"):
            app.find("# ============================================================\\n# Main")
        ],
    "reattach_local_safe":
        "self.sftp_placeholder" in app[
            app.find("def reattach_detached_session"):
            app.find("def reattach_all_detached")
        ],
    "preferences_all":
        "for tab in self.all_terminal_tabs():" in app,
    "appearance_all":
        "for w in self.all_terminal_tabs():" in app,
    "shutdown_all":
        "terminals = self.all_terminal_tabs()" in app[
            app.find("def closeEvent(self, event):", app.find("class MainWindow")):
        ],
    "same_xterm":
        "self.terminal = TerminalWidget(" in app[
            app.find("class LocalShellTerminal"):
            app.find("# ============================================================\\n# Home page")
        ],
    "history": "scrollback: 500000" in html
        and "buildPreservingClearSequence()" in html,
    "selection": "selectHeldClickToTerminalEnd" in html
        and "selectionAutoScrollTimer" in html,
    "clipboard": "copyTerminalSelection" in html,
    "vim_tui": "term.onBinary(function (data)" in html
        and "bracketedPasteMode" in html,
    "glass": 'data-theme="glass"' in html,
    "security": "AutoAddPolicy" not in app,
}

# No duplicate methods in any class.
dups=[]
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        seen={}
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen.setdefault(child.name, []).append(child.lineno)
        for name, lines in seen.items():
            if len(lines) > 1:
                dups.append((node.name, name, lines))
checks["no_duplicate_methods"] = not dups

failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"[{'OK' if v else 'FAIL'}] {k}")
if dups: print("Duplicates:", dups)
if failed:
    print("\\nTERMINAL PARITY QA FAIL:", ", ".join(failed))
    raise SystemExit(1)
print("\\nTERMINAL PARITY QA: OK")
