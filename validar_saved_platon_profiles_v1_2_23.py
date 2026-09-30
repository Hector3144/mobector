# -*- coding: utf-8 -*-
from pathlib import Path
import ast

root=Path(__file__).resolve().parent
app=(root/"mobhector.pyw").read_text(encoding="utf-8-sig")
tree=ast.parse(app)

load_block=app[
    app.find("normalized_sessions = []"):
    app.find("normalized_sessions.append")
]

save_block=app[
    app.find("def _save_platon_profile"):
    app.find("def connect_saved_platon_profile")
]

connect_block=app[
    app.find("def connect_saved_platon_profile"):
    app.find("def new_platon_session")
]

checks={
    "version":
        'APP_VERSION = "1.4.1"' in app,

    "config_mode":
        '"platon_saved",' in load_block,

    "save_checkbox":
        "Guardar este usuario como sesión Platon" in app,

    "profile_name":
        "self.profile_name = QLineEdit()" in app,

    "save_helper":
        "def _save_platon_profile" in app,

    "saved_auth_mode":
        '"auth_mode": "platon_saved"' in save_block,

    "stable_profile_host":
        '"host": "PLATON"' in save_block
        and '"port": 22' in save_block,

    "password_windows":
        "credential_write_password(" in save_block,

    "endpoint_dialog":
        "class PlatonEndpointDialog" in app
        and "Pega únicamente el comando SSH temporal" in app,

    "read_password_windows":
        "credential_read_password(" in connect_block,

    "runtime_target_user":
        '"_platon_jump_username": target_username' in connect_block,

    "runtime_outer_temp_user":
        '"_platon_outer_username": str(' in connect_block,

    "runtime_temp_port":
        '"port": int(endpoint["port"])' in connect_block,

    "connect_dispatch":
        '== "platon_saved"' in app[
            app.find("def connect_selected"):
            app.find("def _prompt_password")
        ],

    "session_list":
        "⚡ Platon guardado" in app,

    "edit_dialog":
        "class SavedPlatonProfileDialog" in app
        and "Perfil Platon actualizado" in app,

    "delete_credential":
        '"platon_saved"' in app[
            app.find("def delete_session"):
            app.find("def session_context")
        ],

    "default_sftp_home":
        "SFTP Platon en HOME por defecto" in app,

    "no_target_home_force":
        "_platon_target_home" not in app
        and "_platon_sftp_path_only" not in app,

    "security":
        "AutoAddPolicy" not in app,
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
    print("\nSAVED PLATON PROFILES QA FAIL:",", ".join(failed))
    raise SystemExit(1)

print("\nSAVED PLATON PROFILES QA: OK")
