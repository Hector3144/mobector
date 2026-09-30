# -*- coding: utf-8 -*-
"""QA estática: iconos SFTP remotos resueltos por asociación de Windows."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
app = (ROOT / "mobhector.pyw").read_text(encoding="utf-8-sig")
checks = {
    "python_syntax": True,
    "qfileiconprovider_import": "QFileIconProvider" in app,
    "qfileinfo_import": "QFileInfo" in app,
    "shell_icon_provider": "self._shell_icon_provider = QFileIconProvider()" in app,
    "remote_icon_cache": "self._remote_icon_cache = {}" in app,
    "extension_cache_key": 'cache_key = suffix or "<no-extension>"' in app,
    "extension_probe": 'QFileInfo("mobhector_remote" + suffix)' in app,
    "provider_icon_lookup": "self._shell_icon_provider.icon(probe)" in app,
    "folder_icon": "QFileIconProvider.IconType.Folder" in app,
    "file_icon": "QFileIconProvider.IconType.File" in app,
    "tree_item_icon": "item.setIcon(0, self._icon_for_remote_row(row))" in app,
    "remote_name_interactive": "self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)" in app,
    "local_name_interactive": "self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)" in app,
}
try:
    ast.parse(app)
except SyntaxError:
    checks["python_syntax"] = False

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)
if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)
print(f"REMOTE WINDOWS ICONS 1.3.4 QA: OK ({len(checks)} checks)")
