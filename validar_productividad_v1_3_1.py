# -*- coding: utf-8 -*-
"""QA específico de MobHector 1.3.1 Productivity Fusion."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "mobhector.pyw").read_text(encoding="utf-8-sig")
HTML = (ROOT / "assets" / "terminal.html").read_text(encoding="utf-8-sig")

checks: list[tuple[str, bool]] = []
def add(name: str, condition: bool):
    checks.append((name, bool(condition)))

try:
    ast.parse(APP)
    add("python_syntax", True)
except SyntaxError:
    add("python_syntax", False)

# Core y funciones heredadas que deben sobrevivir.
add("version_132_compatible", 'APP_VERSION = "1.5.0"' in APP)
add("quick_connect_preserved", "class QuickConnectDialog" in APP and "def quick_connect" in APP)
add("startup_command_preserved", "startup_command" in APP and "_run_startup_command" in APP)
add("folders_favorites_preserved", '"folder"' in APP and '"favorite"' in APP)
add("terminal_search_preserved", "mobhectorSearchTerminal" in HTML)
add("transcripts_preserved", "start_transcript" in APP and 'LOG_DIR / "Sessions"' in APP)
add("safe_export_preserved", "export_sessions_safe" in APP and 'result.pop("credential_id", None)' in APP)

# Compose Bar.
add("compose_bar_widget", 'self.compose_edit = QLineEdit()' in APP and 'setObjectName("ComposeBar")' in APP)
add("compose_shortcut", 'QKeySequence("Ctrl+Shift+P")' in APP and "focus_compose_bar" in APP)
add("compose_current", "def send_compose_current" in APP and "send_session_command(command)" in APP)
add("compose_multiexec", "def send_command_multiexec" in APP and "enabled_tabs()" in APP)
add(
    "compose_no_double_broadcast",
    "target.terminal.send_session_command(command, focus=False)" in APP
    and "handle_multi_exec_input y evita duplicar el broadcast" in APP,
)
add("compose_risk_guard", "def _command_is_high_risk" in APP and '"rm -rf"' in APP and '"reboot"' in APP)

# Snippets/macros.
add("snippets_dock", 'QDockWidget("Snippets / Macros"' in APP)
add("snippets_shortcut", 'QKeySequence("Ctrl+Shift+B")' in APP)
add("snippets_insert", "def insert_selected_quick_command" in APP and "set_compose_text(command)" in APP)
add("snippets_run_current", "def execute_selected_quick_command" in APP)
add("snippets_run_multiexec", "def execute_selected_quick_command_multiexec" in APP)

# Local shells integrados.
add("local_wsl", 'self.shell_kind == "wsl"' in APP and 'shutil.which("wsl.exe")' in APP)
add("local_git_bash", 'self.shell_kind in ("gitbash", "git-bash", "git")' in APP and '"--login", "-i"' in APP)
add("local_same_conpty", "LocalConPTYChannel" in APP and "LocalShellTerminal" in APP)
add("local_menu_wsl", 'local_shell_menu.addAction("WSL")' in APP)
add("local_menu_git", 'local_shell_menu.addAction("Git Bash")' in APP)

# OSC 7 / SFTP Follow Folder.
add("osc7_parser", "registerOscHandler(7" in HTML and "bridge.reportDirectory(path)" in HTML)
add("osc7_bridge", "directory_changed = Signal(str)" in APP and "def reportDirectory" in APP)
add("osc7_terminal_signal", "self.bridge.directory_changed.connect(self.directory_changed.emit)" in APP)
add("sftp_follow_setting", '"sftp_follow_terminal_folder": True' in APP and "self.sftp_follow = QCheckBox" in APP)
add("sftp_follow_handler", "def _follow_terminal_directory" in APP and "follow_terminal_path(path)" in APP)
add(
    "sftp_follow_home_guard",
    "def follow_terminal_path" in APP
    and 'requested.startswith(home.rstrip("/") + "/")' in APP
    and "if not requested.startswith(\"/\")" in APP,
)
add("no_shell_profile_modification", ">> ~/.bashrc" not in APP and ">> ~/.profile" not in APP)

# Seguridad base.
add("no_new_listener", "0.0.0.0" not in APP)
add("credential_manager_preserved", "credential_write_password" in APP and "credential_read_password" in APP)
add("known_hosts_preserved", "configure_host_key_client" in APP and "KNOWN_HOSTS_FILE" in APP)
add("multiexec_preserved", "class MultiExecPage" in APP and "handle_multi_exec_input" in APP)
add("platon_preserved", "class PlatonConnection" in APP and "platon_saved" in APP)

failed = []
for name, ok in checks:
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)

print(f"PRODUCTIVITY FUSION 1.3.1 QA: OK ({len(checks)} checks)")
