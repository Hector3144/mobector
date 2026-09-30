# -*- coding: utf-8 -*-
from pathlib import Path
import ast

root=Path(__file__).resolve().parent
app=(root/"mobhector.pyw").read_text(encoding="utf-8-sig")
tree=ast.parse(app)

platon=app[
    app.find("class PlatonConnection"):
    app.find("# ============================================================\n# Windows Local Shell")
]

checks={
    "version": 'APP_VERSION = "1.5.1"' in app,
    "parser": "def parse_platon_ssh_command" in app,
    "button": 'QPushButton("⚡ Platon")' in app,
    "none_auth": "transport.auth_none(username)" in app,
    "terminal_su": "def _su_shell" in platon,
    "default_sftp":
        "def _open_isolated_direct_sftp" in platon
        and "resolve_remote_home_and_inbox(" in platon,
    "saved_mode": '"platon_saved"' in app,
    "saved_connector": "def connect_saved_platon_profile" in app,
    "endpoint_only": "class PlatonEndpointDialog" in app,
    "windows_credential":
        "credential_write_password(" in app
        and "credential_read_password(" in app,
    "no_target_sftp":
        "def _open_su_sftp_on_client" not in platon
        and "def _open_isolated_su_sftp" not in platon,
    "no_direct_tcpip": 'kind="direct-tcpip"' not in platon,
    "security": "AutoAddPolicy" not in app,
}

dups=[]
for node in tree.body:
    if isinstance(node,ast.ClassDef):
        seen={}
        for child in node.body:
            if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                seen.setdefault(child.name,[]).append(child.lineno)
        for name,lines in seen.items():
            if len(lines)>1:
                dups.append((node.name,name,lines))

checks["no_duplicate_methods"]=not dups

failed=[]
for name,ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if dups:
    print("Duplicates:",dups)

if failed:
    print("\nPLATON 1.2.19 COMPAT FAIL:",", ".join(failed))
    raise SystemExit(1)

print("\nPLATON 1.2.19 COMPAT: OK")
