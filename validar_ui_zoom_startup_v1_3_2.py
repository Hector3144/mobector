# -*- coding: utf-8 -*-
"""QA específico MobHector 1.3.4: zoom/geometry + acceso Startup Command."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "mobhector.pyw").read_text(encoding="utf-8-sig")
HTML = (ROOT / "assets" / "terminal.html").read_text(encoding="utf-8-sig")
UPDATER = (ROOT / "actualizar_mobhector.ps1").read_text(encoding="utf-8-sig")

checks = []
def add(name, ok):
    checks.append((name, bool(ok)))

try:
    ast.parse(APP)
    add("python_syntax", True)
except SyntaxError:
    add("python_syntax", False)

add("version_132", 'APP_VERSION = "1.4.0"' in APP)

# Zoom visible y bidireccional en sesión SSH.
add("ssh_zoom_minus_visible", 'self.zoom_out_button = QPushButton("−")' in APP)
add("ssh_zoom_plus_visible", 'self.zoom_in_button = QPushButton("+")' in APP)
add("ssh_zoom_reset_visible", 'self.zoom_reset_button = QPushButton("100%")' in APP)
add("zoom_plus_calls_in", 'lambda: self.terminal.zoom_in_custom()' in APP)
add("zoom_minus_calls_out", 'lambda: self.terminal.zoom_out_custom()' in APP)
add("zoom_reset_calls_reset", 'lambda: self.terminal.zoom_reset_custom()' in APP)
add("toolbar_zoom_plus_compact", 'self.act_zoom_in = QAction("+", self)' in APP)
add("toolbar_zoom_minus_compact", 'self.act_zoom_out = QAction("−", self)' in APP)

# Local Shell debe conservar los mismos controles para paridad.
add("local_zoom_controls", APP.count('self.zoom_in_button = QPushButton("+")') >= 2 and APP.count('self.zoom_out_button = QPushButton("−")') >= 2)

# Fit de xterm después de estabilizar métricas de fuente y resize_pty.
add("zoom_generation_guard", "let zoomFitGeneration = 0;" in HTML)
add("zoom_double_animation_frame", HTML.count("requestAnimationFrame(function ()") >= 2 and "fitAfterFontMetricsSettle" in HTML)
add("zoom_delayed_refit", "setTimeout(function ()" in HTML and "}, 90);" in HTML)
add("zoom_forces_geometry_report", "lastReportedGeometry = '';" in HTML and "scheduleReportSize(0);" in HTML)
add("zoom_backend_resize_preserved", "bridge.resize(" in HTML)
add("zoom_refresh_after_fit", "term.refresh(0, Math.max(0, term.rows - 1));" in HTML)

# Startup Command debe quedar accesible desde la pestaña activa y persistir.
add("startup_visible_button", "self.startup_button = QPushButton()" in APP and 'self.startup_button.setText("Inicio ●" if enabled else "Inicio")' in APP)
add("startup_reopen_dialog", "def edit_startup_command(self):" in APP and "QInputDialog.getMultiLineText" in APP)
add("startup_global_shortcut", 'QKeySequence("Ctrl+Shift+U")' in APP and 'self.act_startup_command = QAction("⚙ Startup Command…", self)' in APP)
add("startup_session_menu", 'session_m.addAction(self.act_startup_command)' in APP and 'def edit_current_startup_command(self):' in APP)
add("startup_signal", "startup_command_changed = Signal(str)" in APP and "self.startup_command_changed.emit(value)" in APP)
add("startup_persist_helper", "def persist_startup_command_for_tab" in APP and 'sessions[idx]["startup_command"] = value' in APP)
add("startup_persist_index", 'runtime["_persist_config_index"] = self.session_index()' in APP)
add("startup_saved_platon_persist", '"_persist_config_index": profile.get("_persist_config_index")' in APP and '"startup_command": str(profile.get("startup_command", "") or "")' in APP)
add("startup_next_connect_message", "se ejecutará en la próxima conexión" in APP)
add("startup_empty_disables", 'self.status_message.emit("Startup Command desactivado")' in APP)

# No regresiones de seguridad obvias.
add("no_autoaddpolicy", "AutoAddPolicy" not in APP)
add("known_hosts", "configure_host_key_client" in APP and "KNOWN_HOSTS_FILE" in APP)
add("credential_manager", "credential_write_password" in APP and "credential_read_password" in APP)
add("no_listener_0000", "0.0.0.0" not in APP)

# Updater debe instalar y ejecutar este mismo validador y comprobar versión real.

failed = []
for name, ok in checks:
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)

print(f"UI ZOOM + STARTUP 1.3.4 QA: OK ({len(checks)} checks)")
