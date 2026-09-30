# -*- coding: utf-8 -*-
"""Auditoría automatizada de MobHector 1.4.1.

Uso:
  python qa_mobhector.py --source   # QA de paquete, sin requerir deps/activos CDN
  python qa_mobhector.py            # QA de instalación Windows completa
"""
from __future__ import annotations

import ast
import importlib
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_MODE = "--source" in sys.argv
FAIL = []
WARN = []
PASS = []


def ok(name, detail=""):
    PASS.append(name)
    print(f"[OK]   {name}" + (f" - {detail}" if detail else ""))


def fail(name, detail=""):
    FAIL.append((name, detail))
    print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))


def warn(name, detail=""):
    WARN.append((name, detail))
    print(f"[WARN] {name}" + (f" - {detail}" if detail else ""))


def check(name, condition, detail=""):
    (ok if condition else fail)(name, detail)


def rel_luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    rgb = [int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in rgb
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = rel_luminance(a), rel_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


print("=" * 68)
print("MobHector 1.4.1 - QA / AUDITORIA AUTOMATIZADA")
print("=" * 68)

required = [
    "mobhector.pyw",
    "transfer_engine.py",
    "credential_store.py",
    "host_key_store.py",
    "assets/terminal.html",
    "requirements.txt",
    "mobhector.bat",
]
for item in required:
    check(f"archivo {item}", (ROOT / item).exists())

app_path = ROOT / "mobhector.pyw"
app_text = app_path.read_text(encoding="utf-8-sig")
try:
    tree = ast.parse(app_text)
    ok("sintaxis Python mobhector.pyw")
except SyntaxError as exc:
    fail("sintaxis Python mobhector.pyw", str(exc))
    tree = None

for module in ("transfer_engine.py", "credential_store.py", "host_key_store.py"):
    try:
        ast.parse((ROOT / module).read_text(encoding="utf-8"))
        ok(f"sintaxis {module}")
    except Exception as exc:
        fail(f"sintaxis {module}", str(exc))

# Identidad / branding / autoría.
check("marca MobHector", 'APP_NAME = "MobHector"' in app_text)
check("versión 1.4.1", 'APP_VERSION = "1.4.1"' in app_text)
check("autor HECTOR PEREZ", 'DEVELOPER = "HECTOR PEREZ"' in app_text)
check("alias SGNaomi", 'DEVELOPER_ALIAS = "SGNaomi"' in app_text)
for signature_line in (
    r"      |\      _,,,---,,_",
    r"ZZZzz /,`.-'`'    -.  ;-;;,_",
    r"     |,4-  ) )-,_. ,\ (  `'-'",
    r"    '---''(_/--'  `-'\_)  SGNaomi",
):
    check("firma ASCII", signature_line in app_text, signature_line)

# Seguridad.
host_text = (ROOT / "host_key_store.py").read_text(encoding="utf-8")
check("sin AutoAddPolicy", "AutoAddPolicy" not in app_text)
check("host key TOFU explícito", "PromptHostKeyPolicy" in host_text)
check("known_hosts atómico", "os.replace" in host_text and "mkstemp" in host_text)
check("config escritura atómica", "os.replace(tmp_name, CONFIG_FILE)" in app_text)
check("config persiste credential_id migrado", "if dirty:" in app_text and "save_config(data)" in app_text)
check("config elimina password plano", '"password", "ssh_password", "_password_cache"' in app_text and "session.pop(key, None)" in app_text)
check("Credential Manager Windows", "CredWriteW" in (ROOT / "credential_store.py").read_text(encoding="utf-8"))

# Concurrencia / rendimiento.
check("GUI dispatcher enqueued", "Qt.ConnectionType.QueuedConnection" in app_text)
check("workers retenidos globalmente", "_ACTIVE_WORKERS" in app_text)
check("SFTP dedicado por transferencia", "open_sftp_session" in app_text and "open_sftp_session" in (ROOT / "transfer_engine.py").read_text(encoding="utf-8"))
check("TerminalReader bloqueante", "first = self.channel.recv(65535)" in app_text)
check("health transport <= 1Hz reader", "next_transport_check = now + 1.0" in app_text)
check("salida terminal agrupada", "budget = 512 * 1024" in app_text)
check("buffer xterm O(1)", "self._pending_chars" in app_text)
check("filtro SFTP debounce", "self._filter_timer.setInterval(140)" in app_text)
check("refresh SFTP descarta resultados obsoletos", "_refresh_generation" in app_text and "_display_rows_if_current" in app_text)

# Transferencia / integridad.
transfer_text = (ROOT / "transfer_engine.py").read_text(encoding="utf-8")
check("upload temporal remoto", ".mobhector-part-" in transfer_text)
check("download os.replace", "os.replace(temp_local, local_path)" in transfer_text)
check("100% sólo después de publish", '"stage": "complete"' in transfer_text and "percent = min(percent, 99)" in transfer_text)
check("bloquea archivo sobre directorio remoto", "IsADirectoryError" in transfer_text)

# Terminal / TUI / UX.
check("PTY xterm-256color", 'term="xterm-256color"' in app_text and "get_pty(" in app_text)
check("UTF-8 incremental", "getincrementaldecoder" in app_text)
check("resize PTY con píxeles", "width_pixels=width_pixels" in app_text)
check("reconexión R/Q", "Reintentar conexión" in app_text and "Cerrar esta pestaña SSH" in app_text)
check("MultiExec", "class MultiExecPage" in app_text and "handle_multi_exec_input" in app_text)
check("detach drag mouse", "class DetachableTabBar" in app_text and "detach_tab_by_drag" in app_text)
check("WebEngine reactivate", "QWebEnginePage.LifecycleState.Active" in app_text)
check("clipboard Qt nativo", "QApplication.clipboard()" in app_text and "pasteClipboard" in app_text)

# Apariencia.
check("tema aplicación independiente", '"terminal_theme": "moba"' in app_text)
for mode in ("dark", "light", "coffee", "glass"):
    check(f"tema aplicación {mode}", f'"{mode}"' in app_text)
check("QSS café claro", "COFFEE_QSS" in app_text)

html_path = ROOT / "assets" / "terminal.html"
html = html_path.read_text(encoding="utf-8")
for token in (
    "TERMINAL_THEMES", "customGlyphs: true", "scrollOnEraseInDisplay: true",
    "window.setTerminalTheme", "window.setClipboardPreferences",
    "getBoundingClientRect()", "coffee:", "light:", "glass:", "dark:",
):
    check(f"terminal.html {token}", token in html)

# Contraste de los temas sólidos. ANSI black se excluye en dark porque es
# semánticamente negro; brightBlack sí debe ser visible.
for theme in ("dark", "light", "coffee"):
    match = re.search(rf"{theme}:\{{([^}}]+)\}}", html)
    if not match:
        fail(f"contraste {theme}", "tema no encontrado")
        continue
    colors = dict(re.findall(r"(\w+):'([^']+)'", match.group(1)))
    bg = colors.get("background")
    fg = colors.get("foreground")
    if not (bg and fg and bg.startswith("#") and fg.startswith("#")):
        fail(f"contraste {theme}", "background/foreground no hex")
        continue
    base_ratio = contrast(bg, fg)
    check(f"contraste texto principal {theme}", base_ratio >= 7.0, f"{base_ratio:.2f}:1")
    bad = []
    for name, color in colors.items():
        if name in {"background", "selectionBackground", "cursorAccent", "cursor"}:
            continue
        if theme == "dark" and name == "black":
            continue
        if not color.startswith("#"):
            continue
        ratio = contrast(bg, color)
        if ratio < 4.5:
            bad.append(f"{name}={ratio:.2f}")
    check(f"contraste ANSI {theme}", not bad, ", ".join(bad) if bad else ">=4.5:1")

# JavaScript: parse real con Node cuando exista.
node = shutil.which("node")
if node:
    scripts = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, flags=re.S)
    inline = "\n".join(s for s in scripts if s.strip())
    tmp = ROOT / ".qa_terminal_tmp.js"
    try:
        tmp.write_text(inline, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
        check("sintaxis JavaScript terminal", proc.returncode == 0, proc.stderr.strip())
    finally:
        tmp.unlink(missing_ok=True)
else:
    warn("sintaxis JavaScript terminal", "Node no está instalado; se usaron checks estructurales")

# Tests puros de transferencia.
try:
    sys.path.insert(0, str(ROOT))
    import validar_transferencias
    rc = validar_transferencias.main()
    check("regresión transferencias", rc == 0)
except Exception as exc:
    fail("regresión transferencias", repr(exc))

# Credential store: import seguro y target estable; no se escribe ningún secreto.
try:
    import credential_store as cs
    sample = {"credential_id": "qa123", "username": "qa", "host": "host", "port": 22}
    check("credential target MobHector", cs.target_for(sample) == "MobHector:SSH:qa123")
    if sys.platform.startswith("win"):
        check("Credential Manager disponible en Windows", cs.is_available())
    else:
        ok("credential_store import portable")
except Exception as exc:
    fail("credential_store runtime", repr(exc))

# Host-key test real si Paramiko está disponible.
try:
    import paramiko
    import tempfile
    import host_key_store as hks
    key = paramiko.RSAKey.generate(1024)
    fp = hks.fingerprint_sha256(key)
    check("fingerprint SHA256 host key", fp.startswith("SHA256:"))
    with tempfile.TemporaryDirectory(prefix="mobhector-hostkey-") as td:
        kh = Path(td) / "known_hosts"
        hks.trust_host_key(kh, "qa.example", key.get_name(), key.get_base64())
        loaded = paramiko.HostKeys(str(kh))
        check("persistencia known_hosts", "qa.example" in loaded)
        check("eliminar known_hosts", hks.remove_host(kh, "qa.example") is True)
except ModuleNotFoundError:
    if SOURCE_MODE:
        warn("tests Paramiko", "dependencia no instalada en entorno de auditoría")
    else:
        fail("tests Paramiko", "Paramiko no está instalado")
except Exception as exc:
    fail("tests Paramiko", repr(exc))

# Imports runtime. En source-mode son informativos; el instalador los vuelve
# obligatorios después de instalar requirements.
try:
    import PySide6  # noqa
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa
    from PySide6.QtWebChannel import QWebChannel  # noqa
    ok("runtime PySide6 + WebEngine + WebChannel")
except ModuleNotFoundError as exc:
    (warn if SOURCE_MODE else fail)("runtime PySide6", str(exc))
except Exception as exc:
    fail("runtime PySide6", repr(exc))

# Assets xterm: en paquete fuente pueden descargarse en instalación.
for asset in ("xterm.js", "xterm.css", "xterm-addon-fit.js"):
    exists = (ROOT / "assets" / asset).exists()
    if exists:
        ok(f"asset {asset}")
    elif SOURCE_MODE:
        warn(f"asset {asset}", "el instalador lo descargará sólo si falta")
    else:
        fail(f"asset {asset}", "faltante en instalación")

# Duplicados de funciones/métodos.
if tree is not None:
    import collections
    duplicates = []

    module_names = collections.defaultdict(list)
    for child in tree.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_names[child.name].append(child.lineno)
    for name, lines in module_names.items():
        if len(lines) > 1:
            duplicates.append(f"<module>.{name}:{lines}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names = collections.defaultdict(list)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names[child.name].append(child.lineno)
            for name, lines in names.items():
                if len(lines) > 1:
                    duplicates.append(f"{node.name}.{name}:{lines}")

    check("sin funciones/métodos duplicados", not duplicates, "; ".join(duplicates))



# Auditoría 1.4.1: integridad de rutas, sesiones y rendimiento.
check(
    "cero sesiones al eliminar la última",
    'self.config["sessions"].append(\n                    dict(DEFAULT_SESSION)' not in app_text
)
check(
    "valida nombres remotos de UI",
    "def validate_remote_entry_name" in app_text
)
check(
    "SFTP distingue ENOENT de permisos",
    "def is_sftp_not_found" in app_text
    and "if not is_sftp_not_found(exc):" in app_text
)
check(
    "errores refresh SFTP obsoletos descartados",
    "_refresh_error_if_current" in app_text
)
check(
    "fit terminal debounced",
    "self._fit_timer = QTimer(self)" in app_text
    and "schedule_fit_terminal" in app_text
)
check(
    "QThread reader retenido hasta terminar",
    "_RETIRED_TERMINAL_READERS" in app_text
)
check(
    "Glass global no duplica backdrop terminal",
    "needs_private_glass" in app_text
    and "and not app_is_glass" in app_text
)

transfer_text = (ROOT / "transfer_engine.py").read_text(encoding="utf-8")
check(
    "transfer SFTP distingue ENOENT",
    "def _is_not_found" in transfer_text
    and "if _is_not_found(exc)" in transfer_text
)
check(
    "download bloquea path traversal remoto",
    "def _safe_child_name" in transfer_text
)

for launcher in ("mobhector.bat", "mobhector_debug.bat"):
    launcher_text = (ROOT / launcher).read_text(encoding="ascii")
    check(
        f"{launcher} versión 1.4.1",
        "1.4.1" in launcher_text
    )

# Behavioral security, cancellation and rollback tests replace obsolete script-text checks.
try:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    check("regresión 1.4.1 seguridad, cancelación y rollback", result.returncode == 0,
          result.stderr if result.returncode else "pruebas de comportamiento aprobadas")
except Exception as exc:
    fail("regresión 1.4.1", str(exc))

print("\n" + "=" * 68)
print(f"PASS: {len(PASS)}   WARN: {len(WARN)}   FAIL: {len(FAIL)}")
if WARN:
    print("Warnings:")
    for name, detail in WARN:
        print(f" - {name}: {detail}")
if FAIL:
    print("Fallas:")
    for name, detail in FAIL:
        print(f" - {name}: {detail}")
    print("RESULTADO: RECHAZADO")
    raise SystemExit(1)
print("RESULTADO: APROBADO")
raise SystemExit(0)
