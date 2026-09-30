# -*- coding: utf-8 -*-
"""
MobHector v1.5.0
Cliente SSH/SFTP para Windows con terminal real y transferencias visuales.
PySide6 + Paramiko.
"""

from __future__ import annotations

import os
import sys
import errno
import re
import json
import hashlib
import codecs
import shlex
import stat
import time
import socket
import traceback
import logging
from logging.handlers import RotatingFileHandler
import threading
import posixpath
import subprocess
import ctypes
from ctypes import wintypes
import tempfile
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Callable

from PySide6.QtCore import (
    Qt, QObject, Signal, Slot, QThread, QRunnable, QThreadPool,
    QDir, QTimer, QUrl, QSettings, QProcess, QPoint, QRect, QSize, QFileInfo, QLockFile
)
from PySide6.QtGui import (
    QAction, QFontDatabase, QColor, QPalette, QKeySequence,
    QDesktopServices, QShortcut,
    QPainter, QPen, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QListWidget,
    QListWidgetItem, QTabWidget, QTabBar, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QLineEdit, QToolButton, QMessageBox, QInputDialog,
    QFileDialog, QMenu, QDockWidget, QProgressBar, QStatusBar, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QCheckBox, QComboBox,
    QPlainTextEdit, QHeaderView, QFileSystemModel,
    QTreeView, QStackedWidget, QToolBar, QSlider, QGraphicsBlurEffect, QStyle, QWidgetAction, QFileIconProvider
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel

import paramiko
from terminal_io import AsyncChannelWriter
from x11_forwarding import X11Forwarder, parse_display
from remote_text import decode_document, encode_document
from session_validation import read_sessions
from transfer_engine import upload as transfer_upload, download as transfer_download
from credential_store import (
    CredentialStoreError,
    is_available as credential_store_available,
    new_credential_id,
    has_password as credential_has_password,
    read_password as credential_read_password,
    write_password as credential_write_password,
    delete_password as credential_delete_password,
)
from host_key_store import (
    configure_client as configure_host_key_client,
    parse_unknown_marker,
    parse_mismatch_marker,
    mismatch_marker,
    trust_host_key,
    remove_host as remove_trusted_host,
)


APP_NAME = "MobHector"
APP_VERSION = "1.5.0"
ORG_NAME = "MobHector"
DEVELOPER = "HECTOR PEREZ"
DEVELOPER_ALIAS = "SGNaomi"
SIGNATURE = r"""
      |\      _,,,---,,_
ZZZzz /,`.-'`'    -.  ;-;;,_
     |,4-  ) )-,_. ,\ (  `'-'
    '---''(_/--'  `-'\_)  SGNaomi
""".strip("\n")

APPDATA_ROOT = Path(os.environ.get("APPDATA", str(Path.home())))
CONFIG_DIR = APPDATA_ROOT / "MobHector"
CONFIG_FILE = CONFIG_DIR / "config.json"
KNOWN_HOSTS_FILE = CONFIG_DIR / "known_hosts"
LEGACY_CONFIG_DIR = APPDATA_ROOT / "RusterFilesPro"
LEGACY_CONFIG_FILE = LEGACY_CONFIG_DIR / "config.json"

LOG_DIR = Path(
    os.environ.get(
        "LOCALAPPDATA",
        os.environ.get("TEMP", str(CONFIG_DIR))
    )
) / "MobHector" / "Logs"
LOG_FILE = LOG_DIR / "mobhector.log"

LOGGER = logging.getLogger("MobHector")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False
if not LOGGER.handlers:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=4,
            encoding="utf-8",
        )
    except Exception:
        # El logging nunca debe impedir que el cliente abra.
        handler = logging.NullHandler()
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(threadName)s %(message)s"
        ))
    LOGGER.addHandler(handler)

def _uncaught_exception(exc_type, exc_value, exc_tb):
    LOGGER.critical(
        "Excepción no controlada",
        exc_info=(exc_type, exc_value, exc_tb)
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _uncaught_exception

DEFAULT_SESSION = {
    "name": "",
    "host": "",
    "port": 22,
    "username": "",
    "auth_mode": "key",
    "key_file": str(Path.home() / ".ssh" / "pivote_ed25519"),
    "remember_password": False,
    "credential_id": "",

    # Vacío = home real de login resuelto por SFTP.
    "remote_home": "",

    # Vacío = <home remoto>/archivos_enviados.
    "remote_inbox": "",
}

TEXT_EXTENSIONS = {
    ".txt", ".log", ".conf", ".cfg", ".ini", ".xml", ".json", ".yaml", ".yml",
    ".sh", ".bash", ".ksh", ".csh", ".py", ".pl", ".sql", ".csv", ".md",
    ".html", ".htm", ".properties", ".service", ".socket", ".timer", ".mount",
    ".profile", ".rc", ".env"
}


# ============================================================
# Helpers
# ============================================================

def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def safe_local_start() -> str:
    for p in (Path.home() / "Downloads", Path.home() / "Documents", Path.home()):
        if p.exists() and p.is_dir():
            return str(p)
    return str(Path.home())


def _default_config() -> dict:
    return {
        "sessions": [],
        "last_local_path": safe_local_start(),
        "ui_zoom": 100,
        "terminal_zoom": 100,
        "auto_show_sftp": True,
        "workspace_files_visible": True,
        "workspace_files_width": 455,
        "appearance_mode": "dark",
        "terminal_theme": "moba",
        "terminal_colors_v141_migrated": True,
        "accent_color": "cyan",
        "ui_density": "normal",
        "background_image": "",
        "background_blur": 18,
        "glass_darkness": 68,

        # Terminal
        "terminal_font_family": "Cascadia Mono",
        "terminal_font_size": 14,
        "terminal_cursor_style": "block",
        "terminal_cursor_blink": True,
        "terminal_scrollback": 500000,
        "terminal_history_sticky": True,
        "terminal_protect_scrollback": True,
        "terminal_selection_autoscroll": True,
        "terminal_history_v125_migrated": True,
        "terminal_line_height": 108,
        "terminal_bold_bright": True,
        "terminal_auto_copy_selection": True,
        "terminal_ctrl_v_paste": True,
        "terminal_right_click_paste": True,

        # Mouse / interacción de terminal
        "terminal_click_to_cursor": True,
        "terminal_tui_native_mouse": True,
        "terminal_tui_arrow_fallback": True,
        "terminal_middle_click_paste": False,
        "terminal_bell_style": "none",
        "terminal_word_mode": "unix",
        "terminal_show_scrollbar": True,

        # Comportamiento / interfaz
        "start_maximized": True,
        "restore_window_layout": True,
        "show_toolbar": True,
        "show_statusbar": True,
        "show_sessions_panel": True,
        "sftp_auto_show_on_connect": True,
        "sftp_show_hidden_default": True,
        "sftp_follow_terminal_folder": True,
        "confirm_close_session": True,
        "auto_focus_terminal": True,
        "animated_docks": True,
        "tab_position": "top",
        "show_tab_close_buttons": True,
        "detach_distance": 70,
        "confirm_multiexec": False,
        "toolbar_layout": ["new", "quick_connect", "local", "connect", "compose", "reconnect", "refresh", "sessions", "sftp", "transfers", "multiexec", "search", "recorder", "startup", "appearance", "zoom", "zen", "fullscreen"],
        "toolbar_hidden": [],

        # Productividad estilo MobaXterm / SecureCRT / Termius
        "quick_commands": [
            {"name": "Sistema • Resumen", "command": "hostname; date; uptime"},
            {"name": "Memoria • Uso", "command": "free -mh 2>/dev/null || vmstat 1 2"},
            {"name": "Filesystems • Uso", "command": "df -hT 2>/dev/null || df -k"},
            {"name": "Filesystems • Inodos", "command": "df -ih 2>/dev/null || df -ki"},
            {"name": "Red • IP y rutas", "command": "ip -br addr 2>/dev/null; ip route 2>/dev/null || netstat -rn"},
            {"name": "Red • Puertos escuchando", "command": "ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null || netstat -an"},
            {"name": "Procesos • CPU", "command": "ps -eo pid,ppid,user,%cpu,%mem,etime,cmd --sort=-%cpu 2>/dev/null | head -25"},
            {"name": "Procesos • Memoria", "command": "ps -eo pid,ppid,user,%cpu,%mem,etime,cmd --sort=-%mem 2>/dev/null | head -25"},
            {"name": "Storage • lsblk", "command": "lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS 2>/dev/null || format </dev/null"},
            {"name": "Storage • Multipath", "command": "multipath -ll 2>/dev/null || true"},
            {"name": "LVM • Resumen", "command": "pvs 2>/dev/null; vgs 2>/dev/null; lvs 2>/dev/null"},
            {"name": "Logs • Kernel reciente", "command": "dmesg -T 2>/dev/null | tail -80 || dmesg | tail -80"}
        ],
        "terminal_search_case_sensitive": False,

        # SSH / reconexión / rendimiento
        "ssh_keepalive": 20,
        "ssh_connect_timeout": 12,
        "ssh_auth_timeout": 15,
        "ssh_health_interval": 5,
        "ssh_compression": False,
        "auto_reconnect": False,
        "auto_reconnect_attempts": 3,
        "auto_reconnect_delay": 3,
        "worker_threads": 8,
        "log_level": "INFO",
    }


def _sanitize_config(data: dict) -> dict:
    clean = dict(data or {})
    sessions = []
    for raw in clean.get("sessions", []):
        if not isinstance(raw, dict):
            continue
        session = dict(raw)
        # Defensa en profundidad: secretos nunca se persisten aquí.
        for key in (
            "password", "ssh_password", "_password_cache",
            "passphrase", "_passphrase_cache",
            "_resolved_remote_home", "_resolved_remote_inbox",
            "_ssh_keepalive", "_ssh_connect_timeout",
            "_ssh_auth_timeout", "_ssh_health_interval",
            "_auto_focus_terminal", "_ssh_compression",
            "_auto_reconnect", "_auto_reconnect_attempts",
            "_auto_reconnect_delay", "_sftp_show_hidden_default",
            "_sftp_follow_terminal_folder"
        ):
            session.pop(key, None)
        sessions.append(session)
    clean["sessions"] = sessions
    return clean


def _backup_corrupt_config(path: Path):
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        shutil.copy2(path, target)
        LOGGER.warning("Config inválida respaldada en %s", target)
    except Exception:
        LOGGER.exception("No se pudo respaldar config inválida")


def _migrate_legacy_config_if_needed():
    if CONFIG_FILE.exists() or not LEGACY_CONFIG_FILE.exists():
        return
    try:
        ensure_config_dir()
        legacy = json.loads(LEGACY_CONFIG_FILE.read_text(encoding="utf-8"))
        legacy = _sanitize_config(legacy)
        save_config(legacy)
        LOGGER.info("Configuración migrada desde %s", LEGACY_CONFIG_FILE)
    except Exception:
        LOGGER.exception("No se pudo migrar configuración legacy")


def load_config() -> dict:
    ensure_config_dir()
    _migrate_legacy_config_if_needed()
    default = _default_config()

    if not CONFIG_FILE.exists():
        save_config(default)
        return default

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("La raíz de config.json no es un objeto JSON.")

        dirty = False

        # Enable requested classic colours once for existing dark/default terminals.
        if not data.get("terminal_colors_v141_migrated"):
            if data.get("terminal_theme", "follow") in ("follow", "dark") and data.get("appearance_mode", "dark") in ("dark", "graphite"):
                data["terminal_theme"] = "moba"
            data["terminal_colors_v141_migrated"] = True
            dirty = True

        # Migración 1.2.5: el antiguo valor por defecto era 30.000.
        # Sólo se eleva una vez; después el usuario puede reducirlo si quiere.
        if "terminal_history_v125_migrated" not in data:
            try:
                old_scrollback = int(data.get("terminal_scrollback", 30000))
            except Exception:
                old_scrollback = 30000
            if old_scrollback == 30000:
                data["terminal_scrollback"] = 500000
            data["terminal_history_v125_migrated"] = True
            dirty = True

        for key, value in default.items():
            if key not in data:
                # Evitar compartir la lista mutable del default.
                data[key] = (
                    [dict(item) for item in value]
                    if key in ("sessions", "quick_commands") and isinstance(value, list)
                    else value
                )
                dirty = True

        # Cero sesiones es un estado válido. Una instalación limpia
        # nunca inventa host, usuario ni credenciales.
        if not isinstance(data.get("sessions"), list):
            data["sessions"] = []
            dirty = True

        if data.get("appearance_mode") not in (
            "dark", "light", "coffee", "glass",
            "midnight", "graphite", "forest", "purple", "sepia"
        ):
            data["appearance_mode"] = "dark"
            dirty = True

        if data.get("terminal_theme") not in (
            "follow", "dark", "light", "coffee", "glass",
            "midnight", "forest", "purple", "sepia", "moba", "moba_plain"
        ):
            data["terminal_theme"] = "follow"
            dirty = True

        if data.get("accent_color") not in (
            "cyan", "blue", "green", "purple", "amber", "red", "gray"
        ):
            data["accent_color"] = "cyan"
            dirty = True

        if data.get("ui_density") not in ("compact", "normal", "spacious"):
            data["ui_density"] = "normal"
            dirty = True

        if data.get("terminal_cursor_style") not in (
            "block", "bar", "underline"
        ):
            data["terminal_cursor_style"] = "block"
            dirty = True

        if data.get("log_level") not in ("INFO", "DEBUG", "WARNING"):
            data["log_level"] = "INFO"
            dirty = True

        if data.get("terminal_bell_style") not in (
            "none", "visual", "sound"
        ):
            data["terminal_bell_style"] = "none"
            dirty = True

        if data.get("terminal_word_mode") not in (
            "unix", "strict", "spaces"
        ):
            data["terminal_word_mode"] = "unix"
            dirty = True

        if data.get("tab_position") not in ("top", "bottom"):
            data["tab_position"] = "top"
            dirty = True

        for numeric_key, minimum, maximum, fallback in (
            ("terminal_font_size", 9, 26, 14),
            ("terminal_scrollback", 5000, 1000000, 500000),
            ("terminal_line_height", 90, 160, 108),
            ("ssh_keepalive", 0, 180, 20),
            ("ssh_connect_timeout", 5, 90, 12),
            ("ssh_auth_timeout", 5, 120, 15),
            ("ssh_health_interval", 2, 60, 5),
            ("detach_distance", 30, 220, 70),
            ("auto_reconnect_attempts", 1, 10, 3),
            ("auto_reconnect_delay", 1, 60, 3),
            ("worker_threads", 2, 16, 8),
        ):
            try:
                value = int(data.get(numeric_key, fallback))
            except Exception:
                value = fallback
            value = max(minimum, min(maximum, value))
            if data.get(numeric_key) != value:
                data[numeric_key] = value
                dirty = True

        normalized_quick_commands = []
        for raw_command in data.get("quick_commands", []):
            if not isinstance(raw_command, dict):
                dirty = True
                continue
            name = str(raw_command.get("name", "")).strip()[:120]
            command = str(raw_command.get("command", "")).strip()[:12000]
            if not name or not command:
                dirty = True
                continue
            normalized_quick_commands.append({"name": name, "command": command})
        if normalized_quick_commands != data.get("quick_commands", []):
            data["quick_commands"] = normalized_quick_commands
            dirty = True

        normalized_sessions = []
        for raw_session in data.get("sessions", []):
            if not isinstance(raw_session, dict):
                LOGGER.warning(
                    "Se ignoró una sesión inválida en config.json: %r",
                    type(raw_session).__name__
                )
                dirty = True
                continue

            session = dict(raw_session)

            if session.get("auth_mode") not in (
                "key",
                "password",
                "platon_saved",
            ):
                session["auth_mode"] = (
                    "key" if session.get("key_file") else "password"
                )
                dirty = True

            try:
                port = int(session.get("port", 22) or 22)
            except Exception:
                port = 22
            port = max(1, min(65535, port))
            if session.get("port") != port:
                session["port"] = port
                dirty = True

            for text_key in (
                "name", "host", "username", "key_file",
                "remote_home", "remote_inbox", "startup_command", "folder"
            ):
                value = session.get(text_key, "")
                if value is None:
                    value = ""
                if not isinstance(value, str):
                    value = str(value)
                if session.get(text_key) != value:
                    session[text_key] = value
                    dirty = True

            for secret_key in (
                "password", "ssh_password", "_password_cache",
                "passphrase", "_passphrase_cache",
                "_resolved_remote_home", "_resolved_remote_inbox",
                "_ssh_keepalive", "_ssh_connect_timeout",
                "_ssh_auth_timeout", "_ssh_health_interval",
                "_auto_focus_terminal", "_ssh_compression",
                "_auto_reconnect", "_auto_reconnect_attempts",
                "_auto_reconnect_delay", "_sftp_show_hidden_default",
                "_sftp_follow_terminal_folder"
            ):
                if secret_key in session:
                    session.pop(secret_key, None)
                    dirty = True

            if "remember_password" not in session:
                session["remember_password"] = False
                dirty = True
            else:
                session["remember_password"] = bool(
                    session.get("remember_password")
                )

            if (
                session.get("remember_password")
                and not session.get("credential_id")
            ):
                session["credential_id"] = new_credential_id()
                dirty = True

            normalized_sessions.append(session)

        if normalized_sessions != data.get("sessions", []):
            data["sessions"] = normalized_sessions
            dirty = True

        clean = _sanitize_config(data)
        if clean != data:
            data = clean
            dirty = True

        if dirty:
            save_config(data)

        return data

    except Exception:
        LOGGER.exception(
            "config.json inválido; se restaurarán valores seguros"
        )
        _backup_corrupt_config(CONFIG_FILE)
        save_config(default)
        return default


def save_config(data: dict):
    """Escritura atómica: nunca deja un config.json parcial."""
    ensure_config_dir()
    clean = _sanitize_config(data)
    payload = json.dumps(clean, ensure_ascii=False, indent=2).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(
        prefix="config-",
        suffix=".tmp",
        dir=str(CONFIG_DIR),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, CONFIG_FILE)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def remote_join(base: str, child: str) -> str:
    """
    Une rutas POSIX remotas sin permitir que un hijo absoluto descarte
    accidentalmente la ruta base.
    """
    base = str(base or "").strip()
    child = str(child or "").strip()

    if "\x00" in base or "\x00" in child:
        raise ValueError("La ruta remota contiene un carácter NUL no válido.")

    child = child.lstrip("/")
    if not child:
        return posixpath.normpath(base or "/")

    if not base:
        return posixpath.normpath(child)

    return posixpath.normpath(
        posixpath.join(base, child)
    )


def validate_remote_entry_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("El nombre no puede estar vacío.")
    if value in (".", ".."):
        raise ValueError("Los nombres '.' y '..' no están permitidos.")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(
            "El nombre debe ser un único elemento y no puede contener '/' o '\\'."
        )
    return value


def is_sftp_not_found(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    return getattr(exc, "errno", None) == errno.ENOENT


def ensure_remote_directory(sftp, path: str):
    """Portable mkdir -p implemented only with SFTP operations."""
    target = posixpath.normpath(str(path or "").strip())
    if not target or target == "/":
        return target

    absolute = target.startswith("/")
    current = "/" if absolute else ""

    for component in [p for p in target.split("/") if p]:
        current = remote_join(current, component)

        try:
            info = sftp.stat(current)
        except (IOError, OSError) as exc:
            if not is_sftp_not_found(exc):
                raise

            try:
                sftp.mkdir(current)
            except (IOError, OSError) as mkdir_exc:
                try:
                    info = sftp.stat(current)
                except Exception:
                    raise mkdir_exc
            else:
                info = sftp.stat(current)

        if not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(
                f"Existe una ruta remota que no es directorio: {current}"
            )

    return target


def resolve_remote_home_and_inbox(session: dict, sftp):
    """
    Resolve effective remote paths after SSH authentication.

    Empty home: SFTP normalize('.') -> actual login directory.
    Empty inbox: <home>/archivos_enviados.
    Inbox is created automatically.
    """
    configured_home = str(
        session.get("remote_home", "") or ""
    ).strip()

    home = posixpath.normpath(
        sftp.normalize(configured_home or ".")
    )

    configured_inbox = str(
        session.get("remote_inbox", "") or ""
    ).strip()

    if configured_inbox:
        inbox_candidate = (
            configured_inbox
            if configured_inbox.startswith("/")
            else remote_join(home, configured_inbox)
        )
    else:
        inbox_candidate = remote_join(
            home,
            "archivos_enviados"
        )

    inbox = posixpath.normpath(inbox_candidate)

    # Security: default/custom relative inbox must remain under home.
    if (
        inbox != home
        and not inbox.startswith(home.rstrip("/") + "/")
    ):
        raise PermissionError(
            "La carpeta de envíos debe estar dentro del home remoto."
        )

    ensure_remote_directory(sftp, inbox)

    session["_resolved_remote_home"] = home
    session["_resolved_remote_inbox"] = inbox

    return home, inbox


def human_size(size) -> str:
    try:
        n = float(size)
    except Exception:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if n < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024
    return str(size)


def fmt_mtime(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def human_rate(bytes_per_second) -> str:
    try:
        value = max(0.0, float(bytes_per_second))
    except Exception:
        value = 0.0
    return f"{human_size(value)}/s"


def compact_error(error, limit=520) -> str:
    """Última línea útil de un traceback/error para banners y diálogos."""
    text = str(error or "Error desconocido").replace("\r", "").strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    value = lines[-1] if lines else text
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return value


def human_eta(seconds) -> str:
    try:
        seconds = max(0, int(seconds))
    except Exception:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def transfer_meta(done, total, speed) -> str:
    try:
        done = int(done)
        total = int(total)
        speed = float(speed)
    except Exception:
        return ""
    parts = []
    if total > 0:
        parts.append(f"{human_size(done)} / {human_size(total)}")
    if speed > 0:
        parts.append(human_rate(speed))
        remaining = max(0, total - done)
        if remaining and speed > 0:
            parts.append(f"ETA {human_eta(remaining / speed)}")
    return "  •  ".join(parts)


def is_text_candidate(name: str, size: int) -> bool:
    if size > 3 * 1024 * 1024:
        return False
    ext = Path(name.lower()).suffix
    return ext in TEXT_EXTENSIONS or "." not in Path(name).name



# ============================================================
# Appearance / background
# ============================================================

def palette_for_mode(mode: str) -> QPalette:
    pal = QPalette()
    if mode == "light":
        pal.setColor(QPalette.ColorRole.Window, QColor("#f3f6f9"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#17212b"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f1f5f8"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#111a22"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#17212b"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#b9e4e7"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0c2023"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#111820"))
    elif mode in ("coffee", "sepia"):
        pal.setColor(QPalette.ColorRole.Window, QColor("#f3eadc"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#382b23"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#fffaf2"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f3e8d7"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#30251e"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#efe1ce"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#352820"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#d9bd98"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#2a1f18"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#fff7eb"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#34271f"))
    else:
        pal.setColor(QPalette.ColorRole.Window, QColor("#090b0f"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#d6dce6"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#0b0e13"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#0e1117"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#d6dce6"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#151a22"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#d6dce6"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#1d4d55"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#171c24"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    return pal

class BackdropWidget(QWidget):
    """
    Fondo central estable.

    Glass usa una imagen estática cacheada y una capa de oscurecimiento.
    El reescalado se hace con debounce para no competir con QtWebEngine
    cuando se abre/redimensiona una sesión SSH.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("backdropWidget")

        self.mode = "dark"
        self.image_path = ""
        self.blur_radius = 18
        self.darkness = 68

        self.bg = QLabel(self)
        self.bg.setObjectName("glassBackground")
        self.bg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bg.setScaledContents(False)
        self.bg.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.bg.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.dim = QFrame(self)
        self.dim.setObjectName("glassDim")
        self.dim.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.dim.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(0)

        self._content_widget = None
        self._source_pixmap = QPixmap()
        self._rendered_pixmap = QPixmap()
        self._render_key = None
        self._source_key = None

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_background)

        self.bg.hide()
        self.dim.hide()

    def set_content(self, widget):
        if self._content_widget is not None:
            self.content.removeWidget(self._content_widget)

        self._content_widget = widget
        self.content.addWidget(widget)
        self.ensure_layers()

    def configure(
        self,
        mode,
        image_path="",
        blur_radius=18,
        darkness=68
    ):
        new_mode = mode or "dark"
        new_path = image_path or ""
        new_blur = max(0, min(50, int(blur_radius)))
        new_darkness = max(0, min(92, int(darkness)))

        source_key = (
            new_path,
            os.path.getmtime(new_path)
            if new_path and os.path.isfile(new_path)
            else None
        )

        source_changed = source_key != self._source_key
        render_settings_changed = (
            new_mode != self.mode
            or new_blur != self.blur_radius
        )

        self.mode = new_mode
        self.image_path = new_path
        self.blur_radius = new_blur
        self.darkness = new_darkness

        if source_changed:
            self._source_key = source_key

            # La imagen se carga independientemente del modo actual.
            # Así Dark/Light + "terminal Glass" puede usarla y un cambio
            # posterior a Glass no deja _source_pixmap vacío.
            if (
                self.image_path
                and os.path.isfile(self.image_path)
            ):
                self._source_pixmap = QPixmap(self.image_path)
            else:
                self._source_pixmap = QPixmap()

            self._rendered_pixmap = QPixmap()
            self._render_key = None

        elif (
            self.image_path
            and os.path.isfile(self.image_path)
            and self._source_pixmap.isNull()
        ):
            # Defensa para configuraciones creadas por versiones anteriores.
            self._source_pixmap = QPixmap(self.image_path)
            self._rendered_pixmap = QPixmap()
            self._render_key = None

        if render_settings_changed:
            self._render_key = None

        self._apply_layer_state()
        self.ensure_layers()

        if self.mode == "glass" and not self._source_pixmap.isNull():
            self.schedule_refresh(immediate=True)

    def _apply_layer_state(self):
        if self.mode == "glass" and not self._source_pixmap.isNull():
            alpha = round(255 * self.darkness / 100)
            self.dim.setStyleSheet(
                f"background: rgba(3, 5, 8, {alpha}); border: none;"
            )
            self.bg.show()
            self.dim.show()
        else:
            # Dark/light NO conservan ninguna capa Glass previa.
            self.bg.clear()
            self.bg.hide()
            self.dim.clearMask()
            self.dim.setStyleSheet("background: transparent; border: none;")
            self.dim.hide()

    def ensure_layers(self):
        """
        Mantiene siempre:
          fondo < oscurecimiento < contenido.
        Las capas decorativas tampoco capturan el mouse.
        """
        self.bg.setGeometry(self.rect())
        self.dim.setGeometry(self.rect())

        self.bg.lower()
        self.dim.raise_()

        if self._content_widget is not None:
            self._content_widget.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ensure_layers()

        # Abrir una pestaña con QWebEngine dispara muchos resizeEvent.
        # No reescalar la imagen en cada uno.
        if self.mode == "glass" and not self._source_pixmap.isNull():
            self.schedule_refresh()

    def schedule_refresh(self, immediate=False):
        if self.mode != "glass" or self._source_pixmap.isNull():
            return

        self._render_timer.stop()
        self._render_timer.start(0 if immediate else 120)

    def _render_background(self):
        if self.mode != "glass" or self._source_pixmap.isNull():
            return

        size = self.size()
        if size.width() < 2 or size.height() < 2:
            return

        key = (
            size.width(),
            size.height(),
            self.blur_radius,
            self._source_key
        )

        if key == self._render_key and not self._rendered_pixmap.isNull():
            self.bg.setPixmap(self._rendered_pixmap)
            self.bg.show()
            self.ensure_layers()
            return

        try:
            # Escalar/cortar una sola vez cuando termina el resize.
            scaled = self._source_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )

            x = max(0, (scaled.width() - size.width()) // 2)
            y = max(0, (scaled.height() - size.height()) // 2)
            cropped = scaled.copy(
                x, y, size.width(), size.height()
            )

            # El blur en vivo de un QLabel grande puede pelear con
            # Chromium/QtWebEngine. Se renderiza off-screen y luego se
            # muestra como pixmap normal.
            if self.blur_radius > 0:
                cropped = self._blur_pixmap(
                    cropped,
                    self.blur_radius
                )

            self._rendered_pixmap = cropped
            self._render_key = key
            self.bg.setPixmap(self._rendered_pixmap)
            self.bg.show()
            self.ensure_layers()

        except Exception:
            LOGGER.exception("Error renderizando fondo Glass")
            # Ante cualquier problema gráfico, mantener la app usable.
            self.bg.hide()

    @staticmethod
    def _blur_pixmap(pixmap, radius):
        if pixmap.isNull() or radius <= 0:
            return pixmap

        # Import local para no aumentar el coste de inicio en temas sólidos.
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import (
            QGraphicsScene,
            QGraphicsPixmapItem,
            QGraphicsBlurEffect,
        )

        original_size = pixmap.size()
        working = pixmap
        working_radius = float(radius)

        # Blur sobre 4K/ultrawide completo es caro. Para Glass no hace falta
        # procesar cada píxel a resolución nativa: se desenfoca una copia
        # reducida y se vuelve a escalar con filtrado suave. Visualmente es
        # equivalente y reduce mucho CPU/memoria al redimensionar ventanas.
        max_dimension = max(
            original_size.width(),
            original_size.height()
        )
        if max_dimension > 1600:
            scale = 1600.0 / float(max_dimension)
            working = pixmap.scaled(
                max(1, int(original_size.width() * scale)),
                max(1, int(original_size.height() * scale)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            working_radius = max(1.0, float(radius) * scale)

        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(working)

        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(working_radius)
        effect.setBlurHints(
            QGraphicsBlurEffect.BlurHint.QualityHint
        )
        item.setGraphicsEffect(effect)

        scene.addItem(item)
        scene.setSceneRect(
            0,
            0,
            working.width(),
            working.height()
        )

        image = QImage(
            working.size(),
            QImage.Format.Format_ARGB32_Premultiplied
        )
        image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(image)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            True
        )
        scene.render(
            painter,
            QRectF(0, 0, working.width(), working.height()),
            QRectF(0, 0, working.width(), working.height())
        )
        painter.end()

        item.setGraphicsEffect(None)
        scene.clear()

        result = QPixmap.fromImage(image)
        if result.size() != original_size:
            result = result.scaled(
                original_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return result

    def refresh_after_session_open(self):
        """
        Llamado al crear/cambiar una sesión.
        No recarga la imagen desde disco: sólo reafirma stacking y
        programa un único render después de que WebEngine se estabilice.
        """
        self.ensure_layers()

        if self.mode == "glass" and not self._source_pixmap.isNull():
            QTimer.singleShot(80, self.ensure_layers)
            QTimer.singleShot(180, self.schedule_refresh)


class AboutDialog(QDialog):
    """Acerca de con firma monoespaciada para conservar el ASCII art."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acerca de MobHector")
        self.setMinimumWidth(650)

        lay = QVBoxLayout(self)

        brand = QLabel("MobHector")
        brand.setObjectName("homeTitle")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(brand)

        version = QLabel(f"Versión {APP_VERSION}")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(version)

        description = QLabel(
            "Cliente SSH/SFTP para Windows con terminal xterm.js, "
            "MultiExec, Quick Connect, comandos rápidos, búsqueda, transcripts, "
            "credenciales seguras y verificación de claves SSH."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(description)

        developer = QLabel(
            f"Desarrollado por {DEVELOPER} — alias {DEVELOPER_ALIAS}"
        )
        developer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        developer.setObjectName("cardTitle")
        lay.addWidget(developer)

        signature = QPlainTextEdit()
        signature.setReadOnly(True)
        signature.setPlainText(SIGNATURE)
        signature.setFrameShape(QFrame.Shape.NoFrame)
        signature.setStyleSheet("background: transparent; border: none;")
        signature.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        signature.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        signature.setMaximumHeight(120)
        fixed = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont
        )
        fixed.setFamily("Cascadia Mono")
        fixed.setPointSize(11)
        signature.setFont(fixed)
        lay.addWidget(signature)

        stack = QLabel(
            "PySide6 • Qt WebEngine • xterm.js • Paramiko"
        )
        stack.setObjectName("muted")
        stack.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(stack)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


class AppearanceDialog(QDialog):
    """Tema general, acento, densidad y fondo de terminal."""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apariencia")
        self.setMinimumWidth(730)
        self.config = config

        lay = QVBoxLayout(self)

        title = QLabel("Apariencia de MobHector")
        title.setObjectName("homeTitle")
        lay.addWidget(title)

        form = QFormLayout()

        self.mode = QComboBox()
        for label, value in (
            ("Negro / oscuro", "dark"),
            ("Blanco / claro", "light"),
            ("Café claro", "coffee"),
            ("Midnight Blue", "midnight"),
            ("Graphite", "graphite"),
            ("Forest Dark", "forest"),
            ("Purple Night", "purple"),
            ("Sepia cálido", "sepia"),
            ("Glass con imagen", "glass"),
        ):
            self.mode.addItem(label, value)

        idx = self.mode.findData(config.get("appearance_mode", "dark"))
        self.mode.setCurrentIndex(max(0, idx))
        form.addRow("Toda la aplicación:", self.mode)

        self.terminal_theme = QComboBox()
        for label, value in (
            ("Seguir tema de la aplicación", "follow"),
            ("Moba clásico · colores y resaltado", "moba"),
            ("Moba clásico · sólo colores ANSI", "moba_plain"),
            ("Negro", "dark"),
            ("Blanco", "light"),
            ("Café claro", "coffee"),
            ("Midnight Blue", "midnight"),
            ("Forest Dark", "forest"),
            ("Purple Night", "purple"),
            ("Sepia", "sepia"),
            ("Glass / transparente", "glass"),
        ):
            self.terminal_theme.addItem(label, value)

        t_idx = self.terminal_theme.findData(
            config.get("terminal_theme", "follow")
        )
        self.terminal_theme.setCurrentIndex(max(0, t_idx))
        form.addRow("Sólo la terminal:", self.terminal_theme)

        self.accent = QComboBox()
        for label, value in (
            ("Cyan / MobHector", "cyan"),
            ("Azul", "blue"),
            ("Verde", "green"),
            ("Morado", "purple"),
            ("Ámbar", "amber"),
            ("Rojo", "red"),
            ("Gris", "gray"),
        ):
            self.accent.addItem(label, value)
        aidx = self.accent.findData(config.get("accent_color", "cyan"))
        self.accent.setCurrentIndex(max(0, aidx))
        form.addRow("Color de acento:", self.accent)

        self.density = QComboBox()
        self.density.addItem("Compacta", "compact")
        self.density.addItem("Normal", "normal")
        self.density.addItem("Espaciosa", "spacious")
        didx = self.density.findData(config.get("ui_density", "normal"))
        self.density.setCurrentIndex(max(0, didx))
        form.addRow("Densidad de interfaz:", self.density)

        image_box = QWidget()
        image_lay = QHBoxLayout(image_box)
        image_lay.setContentsMargins(0, 0, 0, 0)
        self.image = QLineEdit(config.get("background_image", ""))
        self.image.setPlaceholderText("Imagen JPG/PNG/WEBP para Glass")
        image_lay.addWidget(self.image, 1)
        browse = QPushButton("Elegir imagen")
        browse.clicked.connect(self.choose_image)
        image_lay.addWidget(browse)
        form.addRow("Imagen Glass:", image_box)

        blur_box = QWidget()
        blur_lay = QHBoxLayout(blur_box)
        blur_lay.setContentsMargins(0, 0, 0, 0)
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, 50)
        self.blur_slider.setValue(int(config.get("background_blur", 18)))
        self.blur_value = QLabel(str(self.blur_slider.value()))
        self.blur_slider.valueChanged.connect(
            lambda v: self.blur_value.setText(str(v))
        )
        blur_lay.addWidget(self.blur_slider, 1)
        blur_lay.addWidget(self.blur_value)
        form.addRow("Desenfoque Glass:", blur_box)

        darkness_box = QWidget()
        darkness_lay = QHBoxLayout(darkness_box)
        darkness_lay.setContentsMargins(0, 0, 0, 0)
        self.darkness_slider = QSlider(Qt.Orientation.Horizontal)
        self.darkness_slider.setRange(15, 92)
        self.darkness_slider.setValue(int(config.get("glass_darkness", 68)))
        self.darkness_value = QLabel(f"{self.darkness_slider.value()}%")
        self.darkness_slider.valueChanged.connect(
            lambda v: self.darkness_value.setText(f"{v}%")
        )
        darkness_lay.addWidget(self.darkness_slider, 1)
        darkness_lay.addWidget(self.darkness_value)
        form.addRow("Oscurecer Glass:", darkness_box)

        lay.addLayout(form)

        note = QLabel(
            "El tema de la terminal es independiente. Por ejemplo, puedes "
            "usar MobHector blanco con terminal negra, Forest con terminal "
            "Sepia o MobHector Dark con SÓLO la terminal Glass. En ese último "
            "caso la imagen seleccionada se renderiza exclusivamente detrás "
            "del terminal. El acento no altera los colores ANSI del shell."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar imagen de fondo",
            str(Path.home()),
            "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp);;Todos (*.*)"
        )
        if path:
            self.image.setText(path)

    def value(self):
        return {
            "appearance_mode": self.mode.currentData(),
            "terminal_theme": self.terminal_theme.currentData(),
            "accent_color": self.accent.currentData(),
            "ui_density": self.density.currentData(),
            "background_image": self.image.text().strip(),
            "background_blur": self.blur_slider.value(),
            "glass_darkness": self.darkness_slider.value(),
        }


class TerminalSettingsDialog(QDialog):
    """Terminal, mouse, cursor, selección y portapapeles."""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de Terminal")
        self.setMinimumSize(760, 650)

        root = QVBoxLayout(self)
        title = QLabel("Terminal")
        title.setObjectName("homeTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        display_page = QWidget()
        form = QFormLayout(display_page)

        self.font_family = QComboBox()
        families = [
            "Cascadia Mono", "Cascadia Code", "Consolas",
            "JetBrains Mono", "Fira Code", "Courier New", "monospace",
        ]
        for family in families:
            self.font_family.addItem(family, family)
        current_font = config.get("terminal_font_family", "Cascadia Mono")
        fidx = self.font_family.findData(current_font)
        if fidx < 0:
            self.font_family.addItem(current_font, current_font)
            fidx = self.font_family.count() - 1
        self.font_family.setCurrentIndex(fidx)
        form.addRow("Fuente:", self.font_family)

        self.font_size = QSpinBox()
        self.font_size.setRange(9, 26)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(int(config.get("terminal_font_size", 14)))
        form.addRow("Tamaño base:", self.font_size)

        self.cursor_style = QComboBox()
        self.cursor_style.addItem("Bloque", "block")
        self.cursor_style.addItem("Barra", "bar")
        self.cursor_style.addItem("Subrayado", "underline")
        cidx = self.cursor_style.findData(config.get("terminal_cursor_style", "block"))
        self.cursor_style.setCurrentIndex(max(0, cidx))
        form.addRow("Cursor:", self.cursor_style)

        self.cursor_blink = QCheckBox("Cursor parpadeante")
        self.cursor_blink.setChecked(bool(config.get("terminal_cursor_blink", True)))
        form.addRow("", self.cursor_blink)

        self.scrollback = QSpinBox()
        self.scrollback.setRange(5000, 1000000)
        self.scrollback.setSingleStep(50000)
        self.scrollback.setSuffix(" líneas")
        self.scrollback.setValue(
            int(config.get("terminal_scrollback", 500000))
        )
        self.scrollback.setToolTip(
            "Hasta 1.000.000 de líneas visibles por terminal. Valores altos "
            "consumen más memoria cuando hay muchas sesiones abiertas."
        )
        form.addRow("Historial visible:", self.scrollback)

        self.history_sticky = QCheckBox(
            "Mantener mi posición cuando estoy revisando historial"
        )
        self.history_sticky.setChecked(
            bool(config.get("terminal_history_sticky", True))
        )
        self.history_sticky.setToolTip(
            "La nueva salida SSH no te devuelve al final mientras estás "
            "revisando líneas anteriores."
        )
        form.addRow("", self.history_sticky)

        self.protect_scrollback = QCheckBox(
            "Proteger historial contra clear / borrado remoto de scrollback"
        )
        self.protect_scrollback.setChecked(
            bool(config.get("terminal_protect_scrollback", True))
        )
        self.protect_scrollback.setToolTip(
            "Bloquea únicamente CSI 3 J (Erase Scrollback). "
            "La pantalla puede limpiarse, pero las líneas anteriores "
            "siguen disponibles al subir."
        )
        form.addRow("", self.protect_scrollback)

        self.selection_autoscroll = QCheckBox(
            "Auto-scroll al seleccionar texto hacia arriba/abajo"
        )
        self.selection_autoscroll.setChecked(
            bool(config.get("terminal_selection_autoscroll", True))
        )
        self.selection_autoscroll.setToolTip(
            "Mantén clic izquierdo y arrastra al borde superior/inferior "
            "para continuar seleccionando texto largo."
        )
        form.addRow("", self.selection_autoscroll)

        self.line_height = QSpinBox()
        self.line_height.setRange(90, 160)
        self.line_height.setSuffix("%")
        self.line_height.setValue(int(config.get("terminal_line_height", 108)))
        form.addRow("Altura de línea:", self.line_height)

        self.bold_bright = QCheckBox("Texto ANSI bold usa colores bright")
        self.bold_bright.setChecked(bool(config.get("terminal_bold_bright", True)))
        form.addRow("", self.bold_bright)

        self.show_scrollbar = QCheckBox("Mostrar barra de desplazamiento del terminal")
        self.show_scrollbar.setChecked(bool(config.get("terminal_show_scrollbar", True)))
        form.addRow("", self.show_scrollbar)

        self.bell_style = QComboBox()
        self.bell_style.addItem("Desactivada", "none")
        self.bell_style.addItem("Visual", "visual")
        self.bell_style.addItem("Sonido", "sound")
        bidx = self.bell_style.findData(config.get("terminal_bell_style", "none"))
        self.bell_style.setCurrentIndex(max(0, bidx))
        form.addRow("Campana terminal:", self.bell_style)
        tabs.addTab(display_page, "Pantalla")

        mouse_page = QWidget()
        mouse_lay = QVBoxLayout(mouse_page)

        self.click_to_cursor = QCheckBox(
            "Clic izquierdo posiciona el cursor en la línea actual"
        )
        self.click_to_cursor.setChecked(bool(config.get("terminal_click_to_cursor", True)))
        self.click_to_cursor.setToolTip(
            "PRUEBA| -> clic entre R/U -> PR|UEBA. En shell mueve el cursor "
            "de la línea actual usando flechas."
        )
        mouse_lay.addWidget(self.click_to_cursor)

        click_info = QLabel(
            "Shell: MobHector no reescribe el comando; sólo calcula la "
            "posición y envía flechas."
        )
        click_info.setWordWrap(True)
        click_info.setObjectName("muted")
        mouse_lay.addWidget(click_info)

        self.tui_native_mouse = QCheckBox(
            "Permitir mouse nativo en Vim / TUI cuando la aplicación lo active"
        )
        self.tui_native_mouse.setChecked(
            bool(config.get("terminal_tui_native_mouse", True))
        )
        self.tui_native_mouse.setToolTip(
            "Recomendado. En Vim usa :set mouse=a para activar el protocolo "
            "de mouse real del terminal."
        )
        mouse_lay.addWidget(self.tui_native_mouse)

        self.tui_arrow_fallback = QCheckBox(
            "Fallback Vim/TUI: mover por flechas si la aplicación NO activa mouse"
        )
        self.tui_arrow_fallback.setChecked(
            bool(config.get("terminal_tui_arrow_fallback", True))
        )
        self.tui_arrow_fallback.setToolTip(
            "Si Vim no activa mouse, MobHector mueve el cursor hasta el clic "
            "usando flechas. También puede actuar en otras TUI sin mouse."
        )
        mouse_lay.addWidget(self.tui_arrow_fallback)

        vim_info = QLabel(
            "Para Vim, el modo más preciso es :set mouse=a. Si no está "
            "habilitado, el fallback permite seguir posicionando el cursor. "
            "Los movimientos de mouse no se replican a MultiExec."
        )
        vim_info.setWordWrap(True)
        vim_info.setObjectName("muted")
        mouse_lay.addWidget(vim_info)

        self.middle_paste = QCheckBox("Botón central del mouse pega el portapapeles")
        self.middle_paste.setChecked(bool(config.get("terminal_middle_click_paste", False)))
        mouse_lay.addWidget(self.middle_paste)

        self.auto_copy = QCheckBox("Copiar automáticamente al seleccionar con el mouse")
        self.auto_copy.setChecked(bool(config.get("terminal_auto_copy_selection", True)))
        mouse_lay.addWidget(self.auto_copy)

        self.ctrl_v = QCheckBox("Ctrl+V pega el portapapeles")
        self.ctrl_v.setChecked(bool(config.get("terminal_ctrl_v_paste", True)))
        mouse_lay.addWidget(self.ctrl_v)

        self.right_click = QCheckBox("Clic derecho pega el portapapeles")
        self.right_click.setChecked(bool(config.get("terminal_right_click_paste", True)))
        mouse_lay.addWidget(self.right_click)

        self.word_mode = QComboBox()
        self.word_mode.addItem("Unix / rutas (recomendado)", "unix")
        self.word_mode.addItem("Estricto — separa / : = @ ;", "strict")
        self.word_mode.addItem("Sólo espacios", "spaces")
        widx = self.word_mode.findData(config.get("terminal_word_mode", "unix"))
        self.word_mode.setCurrentIndex(max(0, widx))
        word_form = QFormLayout()
        word_form.addRow("Doble clic selecciona palabras:", self.word_mode)
        mouse_lay.addLayout(word_form)
        mouse_lay.addStretch()
        tabs.addTab(mouse_page, "Mouse / Portapapeles")

        root.addWidget(tabs, 1)
        note = QLabel(
            "Historial recomendado: 500.000 líneas y máximo 1.000.000. "
            "Shift+PageUp/PageDown recorre historial; Ctrl+Shift+Home/End "
            "va al inicio/final. En MultiExec un pegado se replica como un "
            "único bloque a todas las sesiones Activas."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self):
        return {
            "terminal_font_family": self.font_family.currentData(),
            "terminal_font_size": self.font_size.value(),
            "terminal_cursor_style": self.cursor_style.currentData(),
            "terminal_cursor_blink": self.cursor_blink.isChecked(),
            "terminal_scrollback": self.scrollback.value(),
            "terminal_history_sticky": self.history_sticky.isChecked(),
            "terminal_protect_scrollback": (
                self.protect_scrollback.isChecked()
            ),
            "terminal_selection_autoscroll": (
                self.selection_autoscroll.isChecked()
            ),
            "terminal_line_height": self.line_height.value(),
            "terminal_bold_bright": self.bold_bright.isChecked(),
            "terminal_show_scrollbar": self.show_scrollbar.isChecked(),
            "terminal_bell_style": self.bell_style.currentData(),
            "terminal_click_to_cursor": self.click_to_cursor.isChecked(),
            "terminal_tui_native_mouse": self.tui_native_mouse.isChecked(),
            "terminal_tui_arrow_fallback": self.tui_arrow_fallback.isChecked(),
            "terminal_middle_click_paste": self.middle_paste.isChecked(),
            "terminal_word_mode": self.word_mode.currentData(),
            "terminal_auto_copy_selection": self.auto_copy.isChecked(),
            "terminal_ctrl_v_paste": self.ctrl_v.isChecked(),
            "terminal_right_click_paste": self.right_click.isChecked(),
        }


class GeneralSettingsDialog(QDialog):
    """Interfaz, sesiones, SSH, SFTP y rendimiento."""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferencias generales")
        self.setMinimumSize(790, 680)

        root = QVBoxLayout(self)
        title = QLabel("Preferencias generales")
        title.setObjectName("homeTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        ui_page = QWidget()
        ui_lay = QVBoxLayout(ui_page)

        self.start_maximized = QCheckBox("Iniciar maximizado")
        self.start_maximized.setChecked(bool(config.get("start_maximized", True)))
        ui_lay.addWidget(self.start_maximized)

        self.restore_layout = QCheckBox("Restaurar tamaño, posición y distribución de paneles")
        self.restore_layout.setChecked(bool(config.get("restore_window_layout", True)))
        ui_lay.addWidget(self.restore_layout)

        self.show_toolbar = QCheckBox("Mostrar barra de herramientas")
        self.show_toolbar.setChecked(bool(config.get("show_toolbar", True)))
        ui_lay.addWidget(self.show_toolbar)

        self.show_statusbar = QCheckBox("Mostrar barra de estado")
        self.show_statusbar.setChecked(bool(config.get("show_statusbar", True)))
        ui_lay.addWidget(self.show_statusbar)

        self.show_sessions = QCheckBox("Mostrar panel Sesiones al iniciar")
        self.show_sessions.setChecked(bool(config.get("show_sessions_panel", True)))
        ui_lay.addWidget(self.show_sessions)

        self.animated_docks = QCheckBox("Animar paneles acoplables")
        self.animated_docks.setChecked(bool(config.get("animated_docks", True)))
        ui_lay.addWidget(self.animated_docks)

        ui_form = QFormLayout()
        self.tab_position = QComboBox()
        self.tab_position.addItem("Arriba", "top")
        self.tab_position.addItem("Abajo", "bottom")
        tidx = self.tab_position.findData(config.get("tab_position", "top"))
        self.tab_position.setCurrentIndex(max(0, tidx))
        ui_form.addRow("Pestañas:", self.tab_position)

        self.detach_distance = QSpinBox()
        self.detach_distance.setRange(30, 220)
        self.detach_distance.setSuffix(" px")
        self.detach_distance.setValue(int(config.get("detach_distance", 70)))
        self.detach_distance.setToolTip(
            "Distancia fuera de la barra necesaria para desacoplar una pestaña."
        )
        ui_form.addRow("Sensibilidad para desacoplar:", self.detach_distance)
        ui_lay.addLayout(ui_form)

        self.show_tab_close = QCheckBox("Mostrar botón X en las pestañas")
        self.show_tab_close.setChecked(bool(config.get("show_tab_close_buttons", True)))
        ui_lay.addWidget(self.show_tab_close)
        ui_lay.addStretch()
        tabs.addTab(ui_page, "Interfaz")

        sess_page = QWidget()
        sess_lay = QVBoxLayout(sess_page)

        self.sftp_auto = QCheckBox("Mostrar SFTP automáticamente al conectar")
        self.sftp_auto.setChecked(bool(config.get("sftp_auto_show_on_connect", True)))
        sess_lay.addWidget(self.sftp_auto)

        self.sftp_hidden = QCheckBox("Mostrar archivos ocultos por defecto en SFTP")
        self.sftp_hidden.setChecked(bool(config.get("sftp_show_hidden_default", True)))
        sess_lay.addWidget(self.sftp_hidden)

        self.sftp_follow = QCheckBox("SFTP sigue la carpeta del terminal cuando recibe OSC 7")
        self.sftp_follow.setChecked(bool(config.get("sftp_follow_terminal_folder", True)))
        self.sftp_follow.setToolTip(
            "No modifica .bashrc/.profile. Sólo actúa si el shell remoto ya emite OSC 7 "
            "y la ruta permanece dentro del home permitido por SFTP."
        )
        sess_lay.addWidget(self.sftp_follow)

        self.confirm_close = QCheckBox("Confirmar antes de cerrar una sesión SSH conectada")
        self.confirm_close.setChecked(bool(config.get("confirm_close_session", True)))
        sess_lay.addWidget(self.confirm_close)

        self.auto_focus = QCheckBox("Dar foco al terminal después de conectar")
        self.auto_focus.setChecked(bool(config.get("auto_focus_terminal", True)))
        sess_lay.addWidget(self.auto_focus)

        self.confirm_multiexec = QCheckBox(
            "Pedir confirmación adicional antes de activar MultiExec"
        )
        self.confirm_multiexec.setChecked(bool(config.get("confirm_multiexec", False)))
        sess_lay.addWidget(self.confirm_multiexec)

        note = QLabel(
            "La confirmación MultiExec aparece después de escoger las sesiones "
            "y antes de sincronizar el teclado."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        sess_lay.addWidget(note)
        sess_lay.addStretch()
        tabs.addTab(sess_page, "Sesiones / SFTP")

        ssh_page = QWidget()
        ssh_form = QFormLayout(ssh_page)

        self.keepalive = QSpinBox()
        self.keepalive.setRange(0, 180)
        self.keepalive.setSuffix(" s")
        self.keepalive.setSpecialValueText("Desactivado")
        self.keepalive.setValue(int(config.get("ssh_keepalive", 20)))
        ssh_form.addRow("Keepalive SSH:", self.keepalive)

        self.connect_timeout = QSpinBox()
        self.connect_timeout.setRange(5, 90)
        self.connect_timeout.setSuffix(" s")
        self.connect_timeout.setValue(int(config.get("ssh_connect_timeout", 12)))
        ssh_form.addRow("Timeout conexión:", self.connect_timeout)

        self.auth_timeout = QSpinBox()
        self.auth_timeout.setRange(5, 120)
        self.auth_timeout.setSuffix(" s")
        self.auth_timeout.setValue(int(config.get("ssh_auth_timeout", 15)))
        ssh_form.addRow("Timeout autenticación:", self.auth_timeout)

        self.health_interval = QSpinBox()
        self.health_interval.setRange(2, 60)
        self.health_interval.setSuffix(" s")
        self.health_interval.setValue(int(config.get("ssh_health_interval", 5)))
        ssh_form.addRow("Detectar caída cada:", self.health_interval)

        self.ssh_compression = QCheckBox("Habilitar compresión SSH")
        self.ssh_compression.setChecked(bool(config.get("ssh_compression", False)))
        ssh_form.addRow("", self.ssh_compression)

        self.auto_reconnect = QCheckBox(
            "Reconectar automáticamente si se pierde la conexión"
        )
        self.auto_reconnect.setChecked(bool(config.get("auto_reconnect", False)))
        ssh_form.addRow("", self.auto_reconnect)

        self.auto_reconnect_attempts = QSpinBox()
        self.auto_reconnect_attempts.setRange(1, 10)
        self.auto_reconnect_attempts.setValue(int(config.get("auto_reconnect_attempts", 3)))
        ssh_form.addRow("Intentos automáticos:", self.auto_reconnect_attempts)

        self.auto_reconnect_delay = QSpinBox()
        self.auto_reconnect_delay.setRange(1, 60)
        self.auto_reconnect_delay.setSuffix(" s")
        self.auto_reconnect_delay.setValue(int(config.get("auto_reconnect_delay", 3)))
        ssh_form.addRow("Espera entre intentos:", self.auto_reconnect_delay)

        ssh_note = QLabel(
            "La reconexión automática no omite la verificación de host key. "
            "Si la identidad del servidor cambia, MobHector la bloquea."
        )
        ssh_note.setWordWrap(True)
        ssh_note.setObjectName("muted")
        ssh_form.addRow("", ssh_note)
        tabs.addTab(ssh_page, "SSH")

        perf_page = QWidget()
        perf_form = QFormLayout(perf_page)

        self.worker_threads = QSpinBox()
        self.worker_threads.setRange(2, 16)
        self.worker_threads.setValue(int(config.get("worker_threads", 8)))
        perf_form.addRow("Hilos de trabajo:", self.worker_threads)

        self.log_level = QComboBox()
        self.log_level.addItem("Normal (INFO)", "INFO")
        self.log_level.addItem("Diagnóstico (DEBUG)", "DEBUG")
        self.log_level.addItem("Sólo advertencias (WARNING)", "WARNING")
        lidx = self.log_level.findData(config.get("log_level", "INFO"))
        self.log_level.setCurrentIndex(max(0, lidx))
        perf_form.addRow("Nivel de log:", self.log_level)

        perf_note = QLabel(
            "8 workers es el valor recomendado. DEBUG es útil para diagnóstico."
        )
        perf_note.setWordWrap(True)
        perf_note.setObjectName("muted")
        perf_form.addRow("", perf_note)
        tabs.addTab(perf_page, "Rendimiento")

        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self):
        return {
            "start_maximized": self.start_maximized.isChecked(),
            "restore_window_layout": self.restore_layout.isChecked(),
            "show_toolbar": self.show_toolbar.isChecked(),
            "show_statusbar": self.show_statusbar.isChecked(),
            "show_sessions_panel": self.show_sessions.isChecked(),
            "animated_docks": self.animated_docks.isChecked(),
            "tab_position": self.tab_position.currentData(),
            "show_tab_close_buttons": self.show_tab_close.isChecked(),
            "detach_distance": self.detach_distance.value(),
            "sftp_auto_show_on_connect": self.sftp_auto.isChecked(),
            "sftp_show_hidden_default": self.sftp_hidden.isChecked(),
            "sftp_follow_terminal_folder": self.sftp_follow.isChecked(),
            "confirm_close_session": self.confirm_close.isChecked(),
            "auto_focus_terminal": self.auto_focus.isChecked(),
            "confirm_multiexec": self.confirm_multiexec.isChecked(),
            "ssh_keepalive": self.keepalive.value(),
            "ssh_connect_timeout": self.connect_timeout.value(),
            "ssh_auth_timeout": self.auth_timeout.value(),
            "ssh_health_interval": self.health_interval.value(),
            "ssh_compression": self.ssh_compression.isChecked(),
            "auto_reconnect": self.auto_reconnect.isChecked(),
            "auto_reconnect_attempts": self.auto_reconnect_attempts.value(),
            "auto_reconnect_delay": self.auto_reconnect_delay.value(),
            "worker_threads": self.worker_threads.value(),
            "log_level": self.log_level.currentData(),
        }


# ============================================================
# Worker
# ============================================================

class GuiDispatcher(QObject):
    """Ejecuta callbacks en el hilo GUI, sin importar desde qué hilo se pidan."""
    invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(
            self._invoke,
            Qt.ConnectionType.QueuedConnection
        )

    @Slot(object)
    def _invoke(self, callback):
        try:
            callback()
        except Exception:
            traceback.print_exc()


_GUI_DISPATCHER = None
_ACTIVE_WORKERS = {}
_RETIRED_TERMINAL_READERS = set()


def _release_retired_terminal_reader(reader):
    _RETIRED_TERMINAL_READERS.discard(reader)




def run_on_gui(callback):
    """Postea una función al event loop principal de Qt."""
    dispatcher = _GUI_DISPATCHER
    if dispatcher is None:
        # Sólo debería ocurrir durante arranque/pruebas sin QApplication.
        callback()
        return
    dispatcher.invoke.emit(callback)


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    """
    QRunnable seguro para PySide6.

    La operación corre en QThreadPool, pero TODAS las señales de resultado
    se emiten desde el hilo principal a través de GuiDispatcher. Esto evita
    modificar widgets desde un hilo de trabajo cuando el receptor es una
    lambda o un método Python no decorado como @Slot.
    """
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._worker_id = id(self)
        self.setAutoDelete(False)
        _ACTIVE_WORKERS[self._worker_id] = self

    def _post_signal(self, signal, *args, final=False):
        worker_id = self._worker_id
        def deliver():
            try:
                signal.emit(*args)
            finally:
                if final:
                    _ACTIVE_WORKERS.pop(worker_id, None)
        run_on_gui(deliver)

    @Slot()
    def run(self):
        try:
            def safe_progress(payload):
                self._post_signal(self.signals.progress, payload)

            result = self.fn(safe_progress, *self.args, **self.kwargs)
        except Exception:
            error_text = traceback.format_exc()
            LOGGER.error("Worker falló\n%s", error_text)
            self._post_signal(
                self.signals.error,
                error_text,
                final=True
            )
        else:
            self._post_signal(
                self.signals.finished,
                result,
                final=True
            )


# ============================================================
# Session dialog
# ============================================================

def configure_session_x11(owner):
    options = owner._x11_options
    dialog = QDialog(owner)
    dialog.setWindowTitle("X11 · aplicaciones gráficas remotas")
    dialog.setMinimumWidth(600)
    form = QFormLayout(dialog)
    enabled = QCheckBox("Permitir aplicaciones X11 de este servidor de confianza")
    enabled.setChecked(options.get("x11_enabled", False) is True)
    mode = QComboBox()
    if os.name == "nt":
        mode.addItem("Iniciar VcXsrv instalado en Windows", "managed")
    mode.addItem("Usar servidor X11 existente", "existing")
    mode.setCurrentIndex(max(0, mode.findData(options.get("x11_mode", "managed" if os.name == "nt" else "existing"))))
    display = QLineEdit(options.get("x11_display", ""))
    display.setPlaceholderText("Linux: DISPLAY actual; Windows: localhost:0.0")
    authority = QLineEdit(options.get("x11_authority", ""))
    authority.setPlaceholderText("Archivo Xauthority del servidor X (Linux: automático)")
    executable = QLineEdit(options.get("x11_executable", ""))
    executable.setPlaceholderText("Automático: Program Files/VcXsrv/vcxsrv.exe")
    def file_row(field, title):
        box = QWidget(); layout = QHBoxLayout(box); layout.setContentsMargins(0,0,0,0)
        button = QPushButton("Examinar")
        def choose():
            path, _ = QFileDialog.getOpenFileName(dialog, title)
            if path: field.setText(path)
        button.clicked.connect(choose)
        layout.addWidget(field); layout.addWidget(button)
        return box
    form.addRow(enabled)
    form.addRow("Servidor gráfico local:", mode)
    form.addRow("VcXsrv ejecutable:", file_row(executable, "Seleccionar vcxsrv.exe"))
    form.addRow("Display local:", display)
    form.addRow("Xauthority local:", file_row(authority, "Seleccionar archivo Xauthority"))
    hint = QLabel("X11 concede a las aplicaciones remotas acceso a la pantalla X. Actívalo sólo para servidores de confianza. "
                  "VcXsrv se instala aparte; MobHector lo inicia con autenticación y lo cierra al desconectar. "
                  "No desactives el control de acceso del servidor X. Después de guardar, reconecta la sesión SSH.")
    hint.setWordWrap(True); form.addRow(hint)
    def refresh():
        managed = mode.currentData() == "managed"
        executable.setEnabled(managed); display.setEnabled(not managed); authority.setEnabled(not managed)
    mode.currentIndexChanged.connect(refresh); refresh()
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    def save():
        if enabled.isChecked() and mode.currentData() == "existing":
            try: parse_display(display.text().strip() or os.environ.get("DISPLAY", ""))
            except ValueError as error:
                QMessageBox.warning(dialog, "Display X11", str(error)); return
        owner._x11_options = {"x11_enabled": enabled.isChecked(), "x11_mode": mode.currentData(),
            "x11_display": display.text().strip(), "x11_authority": authority.text().strip(),
            "x11_executable": executable.text().strip()}
        owner.x11_button.setText("X11: activado · configurar" if enabled.isChecked() else "X11: desactivado · configurar")
        dialog.accept()
    buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
    dialog.exec()


class SessionDialog(QDialog):
    """
    Editor de sesión con autenticación explícita.

    Para auth=password la contraseña opcional se guarda únicamente en
    Windows Credential Manager; nunca forma parte del dict de sesión.
    """
    def __init__(self, parent=None, session=None):
        super().__init__(parent)

        self._editing_existing = session is not None
        self._original_session = dict(session or {})
        s = dict(session or DEFAULT_SESSION)
        self._x11_options = {k: v for k, v in s.items() if k.startswith("x11_")}

        self.credential_id = (
            str(s.get("credential_id") or "").strip()
            or new_credential_id()
        )

        self._credential_store_ok = credential_store_available()

        credential_probe = dict(s)
        credential_probe["credential_id"] = self.credential_id
        self._credential_exists = (
            credential_has_password(credential_probe)
            if self._credential_store_ok
            else False
        )

        self._result_session = None

        self.setWindowTitle(
            "Nueva sesión SSH"
            if session is None
            else "Editar sesión SSH"
        )
        self.setMinimumWidth(680)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(s.get("name", ""))
        self.host = QLineEdit(s.get("host", ""))

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(s.get("port", 22) or 22))

        self.username = QLineEdit(s.get("username", ""))

        self.auth_mode = QComboBox()
        self.auth_mode.addItem(
            "Llave SSH privada",
            "key"
        )
        self.auth_mode.addItem(
            "Contraseña del usuario",
            "password"
        )

        stored_mode = s.get("auth_mode")
        if stored_mode not in ("key", "password"):
            stored_mode = (
                "key" if s.get("key_file") else "password"
            )
        self.auth_mode.setCurrentIndex(
            0 if stored_mode == "key" else 1
        )

        self.key_file = QLineEdit(
            s.get("key_file", "")
        )
        self.key_file.setPlaceholderText(
            r"C:\Users\usuario\.ssh\id_ed25519"
        )

        self.key_browse = QPushButton("Examinar")
        self.key_browse.clicked.connect(self.choose_key)

        key_box = QWidget()
        key_lay = QHBoxLayout(key_box)
        key_lay.setContentsMargins(0, 0, 0, 0)
        key_lay.addWidget(self.key_file, 1)
        key_lay.addWidget(self.key_browse)

        # Contraseña: nunca se rellena con el secreto guardado.
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Password
        )

        if self._credential_exists:
            self.password_edit.setPlaceholderText(
                "•••••••• guardada en Windows "
                "(déjala vacía para conservarla)"
            )
        else:
            self.password_edit.setPlaceholderText(
                "Escribe la contraseña SSH"
            )

        stored_remember = s.get("remember_password")
        if stored_remember is None:
            # Para sesiones password nuevas/editadas, la opción solicitada
            # queda marcada por defecto; no se persiste hasta guardar.
            stored_remember = stored_mode == "password"

        self.remember_password = QCheckBox(
            "Guardar contraseña en el Administrador "
            "de credenciales de Windows"
        )
        self.remember_password.setChecked(
            bool(stored_remember or self._credential_exists)
        )

        self.credential_status = QLabel()
        self.credential_status.setObjectName("muted")
        self.credential_status.setWordWrap(True)

        self.remote_home = QLineEdit(
            s.get("remote_home", "")
        )
        self.remote_home.setPlaceholderText(
            "Automático — home real del usuario SSH"
        )
        self.remote_home.setToolTip(
            "Déjalo vacío para usar el home real que entrega el servidor "
            "SFTP. No se asume /home/usuario."
        )

        self.remote_inbox = QLineEdit(
            s.get("remote_inbox", "")
        )
        self.remote_inbox.setPlaceholderText(
            "Automático — <home>/archivos_enviados"
        )
        self.remote_inbox.setToolTip(
            "Déjalo vacío para usar <home remoto>/archivos_enviados. "
            "MobHector creará la carpeta si no existe."
        )

        self.folder = QLineEdit(s.get("folder", ""))
        self.folder.setPlaceholderText("Ej.: Producción / SUSE")
        self.folder.setToolTip("Etiqueta visual para organizar sesiones. No modifica SSH.")

        self.startup_command = QLineEdit(s.get("startup_command", ""))
        self.startup_command.setPlaceholderText("Opcional — ej.: hostname; date")
        self.startup_command.setToolTip(
            "Se ejecuta automáticamente al abrir o reconectar esta sesión. "
            "Usa únicamente comandos que hayas revisado."
        )

        self.favorite = QCheckBox("Marcar como favorita ⭐")
        self.favorite.setChecked(bool(s.get("favorite", False)))

        form.addRow("Nombre:", self.name)
        form.addRow("Servidor / IP:", self.host)
        form.addRow("Puerto:", self.port)
        form.addRow("Usuario:", self.username)
        form.addRow("Autenticación:", self.auth_mode)
        form.addRow("Llave SSH:", key_box)
        form.addRow("Contraseña:", self.password_edit)
        form.addRow("", self.remember_password)
        form.addRow("", self.credential_status)
        form.addRow("Grupo / carpeta:", self.folder)
        form.addRow("Home remoto:", self.remote_home)
        form.addRow(
            "Carpeta de envíos:",
            self.remote_inbox
        )
        self.x11_button = QPushButton("X11: activado · configurar" if s.get("x11_enabled") else "X11: desactivado · configurar")
        self.x11_button.clicked.connect(lambda: configure_session_x11(self))
        form.addRow("Aplicaciones gráficas:", self.x11_button)
        form.addRow("Comando al conectar:", self.startup_command)
        form.addRow("", self.favorite)
        lay.addLayout(form)

        self.auth_hint = QLabel()
        self.auth_hint.setObjectName("authHint")
        self.auth_hint.setWordWrap(True)
        lay.addWidget(self.auth_hint)

        security = QLabel(
            "Seguridad: las contraseñas guardadas no se escriben en "
            "config.json. MobHector usa Windows Credential Manager "
            "(credencial genérica, persistencia local) asociado a tu "
            "usuario de Windows."
        )
        security.setObjectName("muted")
        security.setWordWrap(True)
        lay.addWidget(security)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(
            self.validate_accept
        )
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.auth_mode.currentIndexChanged.connect(
            self.update_auth_ui
        )
        self.remember_password.toggled.connect(
            self.update_auth_ui
        )

        self.update_auth_ui()

    def _session_stub(self):
        return {
            "credential_id": self.credential_id,
            "username": self.username.text().strip(),
            "host": self.host.text().strip(),
            "port": self.port.value(),
        }

    def update_auth_ui(self):
        use_key = (
            self.auth_mode.currentData() == "key"
        )

        self.key_file.setEnabled(use_key)
        self.key_browse.setEnabled(use_key)

        password_mode = not use_key
        self.password_edit.setEnabled(
            password_mode
        )
        self.remember_password.setEnabled(
            password_mode
            and self._credential_store_ok
        )

        if use_key:
            self.auth_hint.setText(
                "🔑 Se usará únicamente la llave privada indicada. "
                "Si está protegida con passphrase, MobHector la "
                "solicitará al conectar."
            )
            self.credential_status.setText(
                "La credencial de contraseña se eliminará al guardar "
                "si esta sesión cambia a llave SSH."
                if self._credential_exists
                else ""
            )
            return

        if not self._credential_store_ok:
            self.remember_password.setChecked(False)
            self.auth_hint.setText(
                "🔐 La contraseña se pedirá al conectar. "
                "Windows Credential Manager no está disponible en "
                "este sistema, por lo que no se guardará."
            )
            self.credential_status.setText(
                "⚠ Almacenamiento seguro no disponible."
            )
            return

        if self.remember_password.isChecked():
            self.auth_hint.setText(
                "🔐 MobHector usará la contraseña guardada por "
                "Windows en conexiones futuras y reconexiones."
            )
            if self._credential_exists:
                self.credential_status.setText(
                    "✓ Ya existe una contraseña protegida por Windows. "
                    "Deja el campo Contraseña vacío para conservarla "
                    "o escribe una nueva para reemplazarla."
                )
            else:
                self.credential_status.setText(
                    "Escribe la contraseña antes de guardar esta sesión."
                )
        else:
            self.auth_hint.setText(
                "🔐 La contraseña se pedirá al abrir cada nueva sesión "
                "y sólo permanecerá en RAM mientras la pestaña esté abierta."
            )
            if self._credential_exists:
                self.credential_status.setText(
                    "Al guardar, se eliminará la contraseña actualmente "
                    "guardada en Windows."
                )
            else:
                self.credential_status.setText("")

    def choose_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar llave SSH privada",
            str(Path.home() / ".ssh"),
            "Llaves SSH (*);;Todos (*.*)"
        )
        if path:
            self.key_file.setText(path)

    def _build_value(self):
        home = self.remote_home.text().strip()
        inbox = self.remote_inbox.text().strip()

        if not inbox and home:
            inbox = posixpath.join(
                home,
                "archivos_enviados"
            )

        is_password = (
            self.auth_mode.currentData()
            == "password"
        )

        return {
            "name": (
                self.name.text().strip()
                or self.host.text().strip()
            ),
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "username": self.username.text().strip(),
            "auth_mode": self.auth_mode.currentData(),
            "key_file": os.path.expandvars(
                os.path.expanduser(
                    self.key_file.text().strip()
                )
            ),
            "remember_password": bool(
                is_password
                and self.remember_password.isChecked()
                and self._credential_store_ok
            ),
            "credential_id": self.credential_id,
            "remote_home": home,
            "remote_inbox": inbox,
            "folder": self.folder.text().strip(),
            "startup_command": self.startup_command.text().strip(),
            "favorite": self.favorite.isChecked(),
            **self._x11_options,
        }

    def validate_accept(self):
        if (
            not self.host.text().strip()
            or not self.username.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Sesión SSH",
                "Servidor/IP y usuario son obligatorios."
            )
            return

        if (
            self.auth_mode.currentData() == "key"
            and not self.key_file.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Llave SSH",
                "Selecciona una llave SSH o cambia "
                "Autenticación a Contraseña."
            )
            return

        result = self._build_value()
        password = self.password_edit.text()

        original_identity = (
            str(self._original_session.get("host") or "").strip().casefold(),
            int(self._original_session.get("port", 22) or 22),
            str(self._original_session.get("username") or "").strip(),
        )
        new_identity = (
            str(result.get("host") or "").strip().casefold(),
            int(result.get("port", 22) or 22),
            str(result.get("username") or "").strip(),
        )
        identity_changed = bool(
            self._editing_existing
            and original_identity != new_identity
        )

        # No reutilizar silenciosamente la contraseña de servidor A contra
        # servidor B. Además de ser confuso, enviaría un secreto antiguo a
        # una identidad SSH distinta.
        if (
            result["auth_mode"] == "password"
            and result["remember_password"]
            and identity_changed
            and self._credential_exists
            and not password
        ):
            QMessageBox.warning(
                self,
                "Contraseña",
                "Cambiaste servidor, puerto o usuario. Por seguridad, "
                "escribe nuevamente la contraseña antes de guardar esta "
                "sesión."
            )
            return

        old_credential_session = dict(self._original_session)
        old_credential_session.setdefault(
            "credential_id",
            self.credential_id
        )

        try:
            if result["auth_mode"] == "password":
                if result["remember_password"]:
                    if identity_changed:
                        # Rotar el identificador para que el secreto anterior
                        # nunca quede asociado al nuevo destino.
                        result["credential_id"] = new_credential_id()

                    if password:
                        credential_write_password(
                            result,
                            password
                        )
                        if identity_changed and self._credential_exists:
                            try:
                                credential_delete_password(
                                    old_credential_session
                                )
                            except CredentialStoreError:
                                LOGGER.warning(
                                    "No se pudo limpiar la credencial SSH "
                                    "anterior tras cambiar la identidad",
                                    exc_info=True
                                )
                        self._credential_exists = True
                    elif not self._credential_exists:
                        QMessageBox.warning(
                            self,
                            "Contraseña",
                            "Escribe la contraseña SSH para poder "
                            "guardarla en Windows."
                        )
                        return
                else:
                    if self._credential_exists:
                        credential_delete_password(
                            old_credential_session
                        )
                        self._credential_exists = False
            else:
                # Cambiar a llave elimina la contraseña almacenada de
                # esta sesión para no conservar secretos innecesarios.
                if self._credential_exists:
                    credential_delete_password(
                        old_credential_session
                    )
                    self._credential_exists = False
                result["remember_password"] = False

        except CredentialStoreError as exc:
            QMessageBox.critical(
                self,
                "Administrador de credenciales",
                "Windows no pudo guardar/eliminar la contraseña.\n\n"
                f"{exc}\n\n"
                "La sesión no se modificó."
            )
            return

        # Nunca incluir el campo de contraseña en el resultado.
        result.pop("password", None)
        result.pop("ssh_password", None)

        self._result_session = result
        self.accept()

    def value(self):
        if self._result_session is not None:
            return dict(self._result_session)

        # Camino defensivo; normalmente validate_accept ya lo construyó.
        result = self._build_value()
        result.pop("password", None)
        result.pop("ssh_password", None)
        return result




# ============================================================
# Quick Connect
# ============================================================

class QuickConnectDialog(QDialog):
    """Conexión efímera: no agrega la sesión a config.json."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Connect")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.target = QLineEdit()
        self.target.setPlaceholderText("usuario@servidor:22")
        self.target.setToolTip("Admite usuario@host, usuario@host:puerto o ssh usuario@host -p puerto")
        form.addRow("Destino:", self.target)
        lay.addLayout(form)
        note = QLabel(
            "La conexión es temporal y no se guarda. La contraseña, si se usa, "
            "permanece sólo en RAM durante la pestaña."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @staticmethod
    def parse_target(raw):
        raw = str(raw or "").strip()
        if not raw:
            raise ValueError("Escribe usuario@servidor[:puerto].")
        if raw.lower().startswith("ssh ") or raw.lower().startswith("ssh.exe "):
            tokens = shlex.split(raw, posix=False)
            userhost = ""
            port = 22
            i = 1
            while i < len(tokens):
                token = str(tokens[i]).strip().strip('"').strip("'")
                if token == "-p" and i + 1 < len(tokens):
                    i += 1
                    port = int(str(tokens[i]).strip().strip('"').strip("'"))
                elif not token.startswith("-"):
                    userhost = token
                i += 1
        else:
            userhost = raw
            port = 22

        if "@" not in userhost:
            raise ValueError("Usa el formato usuario@servidor[:puerto].")
        username, hostpart = userhost.rsplit("@", 1)
        username = username.strip()
        hostpart = hostpart.strip()
        if hostpart.startswith("[") and "]" in hostpart:
            close = hostpart.index("]")
            host = hostpart[1:close]
            rest = hostpart[close+1:]
            if rest.startswith(":"):
                port = int(rest[1:])
        elif hostpart.count(":") == 1:
            host, maybe_port = hostpart.rsplit(":", 1)
            if maybe_port.isdigit():
                port = int(maybe_port)
            else:
                host = hostpart
        else:
            host = hostpart
        host = host.strip()
        if not username or not host:
            raise ValueError("Usuario y servidor son obligatorios.")
        port = max(1, min(65535, int(port)))
        return username, host, port

    def validate_accept(self):
        try:
            self.parse_target(self.target.text())
        except Exception as exc:
            QMessageBox.warning(self, "Quick Connect", str(exc))
            return
        self.accept()

    def value(self):
        username, host, port = self.parse_target(self.target.text())
        return {
            "name": f"Quick • {host}",
            "host": host,
            "port": port,
            "username": username,
            "auth_mode": "password",
            "key_file": "",
            "remember_password": False,
            "credential_id": new_credential_id(),
            "remote_home": "",
            "remote_inbox": "",
            "folder": "Quick Connect",
            "startup_command": "",
            "favorite": False,
            "_ephemeral": True,
        }


# ============================================================
# Platon ephemeral SSH/SFTP session
# ============================================================

def parse_platon_ssh_command(command: str) -> dict:
    """
    Acepta principalmente:
        ssh.exe -l USER -p PORT 127.0.0.1
        ssh -p PORT -l USER localhost
        ssh USER@127.0.0.1 -p PORT

    Platon usa endpoints temporales loopback; por seguridad este modo no
    acepta hosts remotos. Para ellos existe la sesión SSH normal.
    """
    raw = str(command or "").strip()
    if not raw:
        raise ValueError("Pega el comando SSH generado por Platon.")

    try:
        tokens = shlex.split(raw, posix=False)
    except Exception as exc:
        raise ValueError(
            "No se pudo interpretar el comando SSH."
        ) from exc

    tokens = [
        str(token).strip().strip('"').strip("'")
        for token in tokens
        if str(token).strip()
    ]

    if not tokens:
        raise ValueError("El comando está vacío.")

    executable = Path(tokens[0]).name.casefold()
    if executable not in ("ssh", "ssh.exe"):
        raise ValueError(
            "El comando debe comenzar con ssh o ssh.exe."
        )

    username = ""
    port = 22
    host = ""
    positional = []

    i = 1
    while i < len(tokens):
        token = tokens[i]
        lower = token.casefold()

        if lower == "-l":
            i += 1
            if i >= len(tokens):
                raise ValueError("Falta el usuario después de -l.")
            username = tokens[i]

        elif lower == "-p":
            i += 1
            if i >= len(tokens):
                raise ValueError("Falta el puerto después de -p.")
            try:
                port = int(tokens[i])
            except Exception as exc:
                raise ValueError("El puerto de Platon no es válido.") from exc

        elif lower in ("-o", "-i", "-f", "-j", "-b", "-c", "-d", "-e", "-m", "-s", "-w"):
            # Opciones OpenSSH que consumen un argumento. Este parser no
            # depende de ellas, pero no debe confundir su valor con el host.
            i += 1
            if i >= len(tokens):
                raise ValueError(
                    f"Falta el valor de la opción {token}."
                )

        elif token.startswith("-"):
            # Otras flags sin argumento.
            pass

        else:
            positional.append(token)

        i += 1

    if positional:
        target = positional[-1]

        if "@" in target:
            target_user, target_host = target.rsplit("@", 1)
            if not username:
                username = target_user
            host = target_host
        else:
            host = target

    username = str(username).strip()
    host = str(host).strip().strip("[]")

    if not username:
        raise ValueError(
            "No pude identificar el usuario. Usa -l USUARIO o USUARIO@HOST."
        )

    if not host:
        raise ValueError("No pude identificar el host.")

    if port < 1 or port > 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535.")

    allowed_hosts = {
        "127.0.0.1",
        "localhost",
        "::1",
    }

    if host.casefold() not in allowed_hosts:
        raise ValueError(
            "El modo Platon sólo admite endpoints locales "
            "(127.0.0.1, localhost o ::1). "
            "Para servidores remotos usa + SSH."
        )

    return {
        "username": username,
        "host": host,
        "port": port,
        "command": raw,
    }


class PlatonCommandDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva sesión Platon / su")
        self.resize(720, 310)
        self._value = None

        root = QVBoxLayout(self)

        title = QLabel("⚡ Platon — Terminal + SFTP + su opcional")
        title.setObjectName("brand")
        root.addWidget(title)

        help_text = QLabel(
            "Pega el comando SSH temporal generado por Platon. "
            "MobHector extraerá usuario, puerto y endpoint local, "
            "intentará autenticación sin contraseña y abrirá una pestaña "
            "con Terminal + SFTP / Archivos."
        )
        help_text.setWordWrap(True)
        root.addWidget(help_text)

        self.command = QPlainTextEdit()
        self.command.setPlaceholderText(
            "ssh.exe -l TmP7aK9Q -p 61234 127.0.0.1"
        )
        self.command.setMaximumHeight(95)
        root.addWidget(self.command)

        self.jump_enabled = QCheckBox(
            "Cambiar a otro usuario con su - después de entrar por Platon"
        )
        self.jump_enabled.setChecked(False)
        self.jump_enabled.setToolTip(
            "Opcional. MobHector reproducirá el flujo manual: "
            "su - USUARIO dentro de la sesión Platon. La terminal "
            "cambiará a ese usuario; SFTP conservará la identidad "
            "Platon y su HOME por defecto."
        )
        root.addWidget(self.jump_enabled)

        self.jump_box = QFrame()
        self.jump_box.setObjectName("platonJumpBox")
        jump_form = QFormLayout(self.jump_box)
        jump_form.setContentsMargins(18, 8, 8, 8)

        self.jump_username = QLineEdit()
        self.jump_username.setPlaceholderText(
            "Ej: C12345678"
        )
        self.jump_username.setEnabled(False)

        self.jump_password = QLineEdit()
        self.jump_password.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.jump_password.setPlaceholderText(
            "Contraseña del usuario destino"
        )
        self.jump_password.setEnabled(False)

        jump_form.addRow(
            "Usuario destino:",
            self.jump_username
        )
        jump_form.addRow(
            "Contraseña:",
            self.jump_password
        )

        jump_note = QLabel(
            "MobHector ejecutará su - USUARIO en el PTY. "
            "SFTP / Archivos seguirá usando la sesión SFTP temporal "
            "de Platon y su HOME por defecto."
        )
        jump_note.setObjectName("muted")
        jump_note.setWordWrap(True)
        jump_form.addRow("", jump_note)

        root.addWidget(self.jump_box)

        self.save_profile = QCheckBox(
            "Guardar este usuario como sesión Platon"
        )
        self.save_profile.setChecked(False)
        self.save_profile.setEnabled(False)
        self.save_profile.setToolTip(
            "Guarda el usuario del su - y protege su contraseña "
            "con Windows Credential Manager."
        )
        root.addWidget(self.save_profile)

        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText(
            "Nombre del perfil, ej: Producción - Unix"
        )
        self.profile_name.setEnabled(False)
        root.addWidget(self.profile_name)

        self.jump_enabled.toggled.connect(
            self.jump_username.setEnabled
        )
        self.jump_enabled.toggled.connect(
            self.jump_password.setEnabled
        )
        self.jump_enabled.toggled.connect(
            self.save_profile.setEnabled
        )
        self.jump_enabled.toggled.connect(
            lambda enabled:
                self.save_profile.setChecked(False)
                if not enabled
                else None
        )
        self.save_profile.toggled.connect(
            self.profile_name.setEnabled
        )
        self.jump_enabled.toggled.connect(
            lambda enabled:
                self.jump_username.setFocus()
                if enabled
                else None
        )

        note = QLabel(
            "Sin marcar Guardar, la sesión es temporal. "
            "Si guardas el perfil, el código Platon nunca se almacena "
            "y la contraseña del su se protege con Windows."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Conectar Platon")
        buttons.accepted.connect(self._accept_command)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.command.setFocus()

    def _accept_command(self):
        try:
            self._value = parse_platon_ssh_command(
                self.command.toPlainText()
            )
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Comando Platon",
                str(exc)
            )
            return

        jump_enabled = bool(
            self.jump_enabled.isChecked()
        )

        jump_username = (
            self.jump_username.text().strip()
            if jump_enabled
            else ""
        )
        jump_password = (
            self.jump_password.text()
            if jump_enabled
            else ""
        )

        if jump_enabled and not jump_username:
            QMessageBox.warning(
                self,
                "Salto de usuario",
                "Escribe el usuario destino."
            )
            self.jump_username.setFocus()
            return

        if jump_enabled and not jump_password:
            QMessageBox.warning(
                self,
                "Salto de usuario",
                "Escribe la contraseña del usuario destino."
            )
            self.jump_password.setFocus()
            return

        save_profile = bool(
            self.save_profile.isChecked()
            and jump_enabled
        )

        if (
            save_profile
            and not credential_store_available()
        ):
            QMessageBox.warning(
                self,
                "Guardar perfil Platon",
                "Windows Credential Manager no está disponible. "
                "No se guardará una contraseña en texto plano."
            )
            return

        profile_name = (
            self.profile_name.text().strip()
            if save_profile
            else ""
        )

        self._value.update(
            {
                "jump_enabled": jump_enabled,
                "jump_username": jump_username,
                "jump_password": jump_password,
                "save_profile": save_profile,
                "profile_name": (
                    profile_name
                    or (
                        f"Platon • {jump_username}"
                        if save_profile
                        else ""
                    )
                ),
            }
        )

        self.accept()

    def value(self):
        return dict(self._value or {})



class PlatonEndpointDialog(QDialog):
    """Para un perfil guardado, pide únicamente el código SSH temporal."""
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = dict(profile or {})
        self._value = None

        self.setWindowTitle("Abrir sesión Platon guardada")
        self.resize(700, 245)

        root = QVBoxLayout(self)

        title = QLabel(
            "⚡ "
            + str(self.profile.get("name", "Sesión Platon"))
        )
        title.setObjectName("brand")
        root.addWidget(title)

        info = QLabel(
            "Usuario del su - guardado: "
            + str(self.profile.get("username", ""))
            + "\n\nPega únicamente el comando SSH temporal "
              "que Platon generó para esta conexión."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.command = QPlainTextEdit()
        self.command.setPlaceholderText(
            "ssh.exe -l R7x9Lm2Q -p 58421 127.0.0.1"
        )
        self.command.setMaximumHeight(90)
        root.addWidget(self.command)

        note = QLabel(
            "El usuario temporal y el puerto no se guardan; "
            "pueden cambiar en cada conexión."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Conectar")
        buttons.accepted.connect(self._accept_command)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.command.setFocus()

    def _accept_command(self):
        try:
            self._value = parse_platon_ssh_command(
                self.command.toPlainText()
            )
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Código Platon",
                str(exc)
            )
            return

        self.accept()

    def value(self):
        return dict(self._value or {})


class SavedPlatonProfileDialog(QDialog):
    """Editar nombre, usuario del su y contraseña guardada."""
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = dict(profile or {})
        self._value = None

        self.setWindowTitle("Editar perfil Platon")
        self.resize(600, 300)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(
            str(self.profile.get("name", ""))
        )

        self.user_edit = QLineEdit(
            str(self.profile.get("username", ""))
        )

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.password_edit.setPlaceholderText(
            "Vacía = conservar la contraseña protegida actual"
        )

        form.addRow("Nombre:", self.name_edit)
        form.addRow("Usuario del su -:", self.user_edit)
        form.addRow("Nueva contraseña:", self.password_edit)
        root.addLayout(form)

        note = QLabel(
            "La contraseña queda en Windows Credential Manager; "
            "nunca se guarda en config.json."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self):
        username = self.user_edit.text().strip()
        name = self.name_edit.text().strip()

        if not username:
            QMessageBox.warning(
                self,
                "Perfil Platon",
                "Escribe el usuario del su -."
            )
            return

        self._value = {
            "name": name or f"Platon • {username}",
            "username": username,
            "new_password": self.password_edit.text(),
        }
        self.accept()

    def value(self):
        return dict(self._value or {})


# ============================================================
# SSH connection
# ============================================================

class SSHConnection(QObject):
    state_changed = Signal(str)

    def __init__(self, session: dict):
        super().__init__()
        self.session = dict(session)
        if self.session.get("auth_mode") not in ("key", "password"):
            self.session["auth_mode"] = (
                "key" if self.session.get("key_file") else "password"
            )
        self.client = None
        self.sftp = None
        self.lock = threading.RLock()
        self.connected = False
        self._x11_forwarder = None

        # Secretos sólo en RAM durante la vida de esta pestaña.
        self._password_cache = None
        self._passphrase_cache = None

    @property
    def auth_mode(self):
        return self.session.get("auth_mode", "key")

    def connect(self, password=None, passphrase=None):
        """Conecta/reconecta respetando exactamente el método seleccionado."""
        with self.lock:
            if password is not None:
                self._password_cache = password
            if passphrase is not None:
                self._passphrase_cache = passphrase

            # Una reconexión destruye handles viejos, pero conserva secretos RAM.
            self._close_handles(emit_state=False)
            self.state_changed.emit("Conectando")

            cli = paramiko.SSHClient()
            configure_host_key_client(
                cli,
                KNOWN_HOSTS_FILE
            )

            kw = {
                "hostname": self.session["host"],
                "port": int(self.session.get("port", 22)),
                "username": self.session["username"],
                "timeout": int(self.session.get("_ssh_connect_timeout", 12)),
                "banner_timeout": int(
                    self.session.get("_ssh_connect_timeout", 12)
                ),
                "auth_timeout": int(self.session.get("_ssh_auth_timeout", 15)),
                # Evitar que Paramiko pruebe métodos distintos al elegido.
                "allow_agent": False,
                "look_for_keys": False,
                "compress": bool(
                    self.session.get("_ssh_compression", False)
                ),
            }

            if self.auth_mode == "password":
                secret = self._password_cache
                if secret is None:
                    raise RuntimeError(
                        "Se requiere la contraseña SSH para esta sesión."
                    )
                kw["password"] = secret
            else:
                key = os.path.expandvars(os.path.expanduser(
                    self.session.get("key_file", "")
                ))
                if not key:
                    raise RuntimeError(
                        "La sesión está configurada con llave SSH, pero no tiene ruta de llave."
                    )
                if not os.path.isfile(key):
                    raise FileNotFoundError(f"No existe la llave SSH: {key}")
                kw["key_filename"] = key
                if self._passphrase_cache:
                    kw["passphrase"] = self._passphrase_cache

            try:
                cli.connect(**kw)
                transport = cli.get_transport()
                if not transport or not transport.is_active():
                    raise RuntimeError("El transporte SSH no quedó activo.")
                keepalive = int(self.session.get("_ssh_keepalive", 20))
                if keepalive > 0:
                    transport.set_keepalive(keepalive)

                sftp = cli.open_sftp()
                resolve_remote_home_and_inbox(
                    self.session,
                    sftp
                )
            except paramiko.BadHostKeyException as exc:
                try:
                    cli.close()
                except Exception:
                    pass
                self.connected = False
                self.state_changed.emit("Desconectado")
                raise RuntimeError(mismatch_marker(exc)) from exc
            except Exception:
                try:
                    cli.close()
                except Exception:
                    pass
                self.connected = False
                self.state_changed.emit("Desconectado")
                raise

            self.client = cli
            self.sftp = sftp
            self.connected = True
            self.state_changed.emit("Conectado")
            return True

    def is_alive(self):
        try:
            transport = self.client.get_transport() if self.client else None
            return bool(
                self.connected
                and transport
                and transport.is_active()
                and transport.is_authenticated()
            )
        except Exception:
            return False

    def get_transport(self):
        try:
            return self.client.get_transport() if self.client else None
        except Exception:
            return None

    def ensure(self):
        """Valida SSH y repara el canal SFTP de navegación si se cerró."""
        with self.lock:
            if not self.is_alive():
                raise RuntimeError("La sesión SSH no está conectada.")

            sftp_ok = False
            if self.sftp is not None:
                try:
                    channel = self.sftp.get_channel()
                    sftp_ok = bool(channel and not channel.closed)
                except Exception:
                    sftp_ok = False

            if not sftp_ok:
                try:
                    if self.sftp is not None:
                        self.sftp.close()
                except Exception:
                    pass
                self.sftp = self.client.open_sftp()

            return True

    def open_sftp_session(self):
        """Nuevo canal SFTP independiente sobre el mismo Transport."""
        # Sólo serializamos la creación del canal contra reconnect/close;
        # la transferencia posterior NO mantiene este lock.
        with self.lock:
            if not self.is_alive():
                raise RuntimeError("La sesión SSH no está conectada.")
            transport = self.get_transport()
            if not transport or not transport.is_active():
                raise RuntimeError("El transporte SSH no está activo.")
            return transport.open_sftp_client()

    def exec(self, command: str, timeout=30):
        """Ejecuta comando en un canal independiente sin bloquear SFTP."""
        with self.lock:
            if not self.is_alive():
                raise RuntimeError("La sesión SSH no está conectada.")
            transport = self.get_transport()
            if not transport or not transport.is_active():
                raise RuntimeError("El transporte SSH no está activo.")
            channel = transport.open_session(timeout=timeout)

        out_chunks = []
        err_chunks = []
        deadline = time.monotonic() + max(1, float(timeout))

        try:
            channel.exec_command(command)
            while True:
                while channel.recv_ready():
                    chunk = channel.recv(65535)
                    if not chunk:
                        break
                    out_chunks.append(chunk)

                while channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(65535)
                    if not chunk:
                        break
                    err_chunks.append(chunk)

                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    break

                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"El comando remoto excedió {timeout}s."
                    )

                time.sleep(0.01)

            status = channel.recv_exit_status()
            return status, b"".join(out_chunks), b"".join(err_chunks)
        finally:
            try:
                channel.close()
            except Exception:
                pass

    def open_shell(
        self,
        width=120,
        height=40,
        width_pixels=0,
        height_pixels=0
    ):
        """
        Crea una sesión interactiva con PTY explícito.

        get_pty(xterm-256color) es la parte importante para vim/less/top/
        tmux/nano/curses. Las variables adicionales son best-effort porque
        sshd puede rechazarlas si AcceptEnv no las permite.
        """
        self.ensure()

        with self.lock:
            transport = self.client.get_transport()
            if not transport or not transport.is_active():
                raise RuntimeError(
                    "El transporte SSH no está activo."
                )

            ch = transport.open_session(
                timeout=int(self.session.get("_ssh_connect_timeout", 12))
            )
            ch.set_name("MobHector-Terminal")

            ch.get_pty(
                term="xterm-256color",
                width=max(20, int(width)),
                height=max(5, int(height)),
                width_pixels=max(0, int(width_pixels)),
                height_pixels=max(0, int(height_pixels)),
            )

            # No se depende de estas variables: muchos sshd las rechazan
            # silenciosamente. TERM ya queda definido por get_pty().
            try:
                ch.update_environment({
                    "COLORTERM": "truecolor",
                    "TERM_PROGRAM": "MobHector",
                    "TERM_PROGRAM_VERSION": APP_VERSION,
                })
            except Exception:
                LOGGER.debug(
                    "Servidor rechazó variables opcionales de terminal",
                    exc_info=True
                )

            try:
                self._enable_x11(ch)
                ch.invoke_shell()
            except Exception:
                ch.close()
                self._close_x11()
                raise
            ch.settimeout(0.2)
            return ch

    def _enable_x11(self, channel):
        if self.session.get("x11_enabled") is not True:
            return
        if self._x11_forwarder is None:
            self._x11_forwarder = X11Forwarder(self.session, self.state_changed.emit)
        self._x11_forwarder.request(channel)
        self.state_changed.emit("Conectado · X11 activo")

    def _close_x11(self):
        forwarder = getattr(self, "_x11_forwarder", None)
        self._x11_forwarder = None
        if forwarder is not None:
            forwarder.close()

    def _close_handles(self, emit_state=True):
        self._close_x11()
        self.connected = False
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.sftp = None
        self.client = None
        if emit_state:
            self.state_changed.emit("Desconectado")

    def clear_password_cache(self):
        with self.lock:
            self._password_cache = None

    def clear_passphrase_cache(self):
        with self.lock:
            self._passphrase_cache = None

    def close(self, clear_secret=True):
        with self.lock:
            self._close_handles(emit_state=True)
            if clear_secret:
                self._password_cache = None
                self._passphrase_cache = None




class PrefetchedSSHChannel:
    """Channel Paramiko con bytes preleídos durante la negociación de su."""
    def __init__(self, channel, prefix=b""):
        self._channel = channel
        self._prefix = bytearray(prefix or b"")

    @property
    def closed(self):
        return bool(self._channel.closed)

    def recv(self, size):
        size = max(1, int(size))
        if self._prefix:
            chunk = bytes(self._prefix[:size])
            del self._prefix[:size]
            return chunk
        return self._channel.recv(size)

    def recv_ready(self):
        return bool(self._prefix) or self._channel.recv_ready()

    def sendall(self, data):
        return self._channel.sendall(data)

    def resize_pty(self, *args, **kwargs):
        return self._channel.resize_pty(*args, **kwargs)

    def close(self):
        return self._channel.close()

    def settimeout(self, value):
        return self._channel.settimeout(value)

    def __getattr__(self, name):
        return getattr(self._channel, name)


class OwnedSFTPClient:
    """
    SFTPClient que posee una conexión SSH auxiliar.

    Se usa sólo para Platon + su. Si el canal SFTP experimental muere,
    la conexión SSH/PTY principal de la terminal permanece intacta.
    """
    def __init__(self, sftp, owner_client):
        self._sftp = sftp
        self._owner_client = owner_client
        self._closed = False

    def get_channel(self):
        return self._sftp.get_channel()

    def close(self):
        if self._closed:
            return
        self._closed = True

        try:
            self._sftp.close()
        except Exception:
            pass

        try:
            self._owner_client.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._sftp, name)


class PlatonSSHClient(paramiko.SSHClient):
    """
    SSHClient normal de Paramiko con una única diferencia:
    después de verificar host-key intenta SSH auth method "none".

    Esto conserva la verificación explícita de host-key de MobHector.
    """
    def _auth(self, username, *args, **kwargs):
        transport = getattr(self, "_transport", None)

        if transport is None:
            raise paramiko.SSHException(
                "El transporte SSH de Platon no existe."
            )

        try:
            transport.auth_none(username)
        except paramiko.BadAuthenticationType as exc:
            methods = ", ".join(
                getattr(exc, "allowed_types", [])
                or []
            )
            raise paramiko.AuthenticationException(
                "El endpoint de Platon no aceptó autenticación SSH 'none'."
                + (
                    f" Métodos ofrecidos: {methods}"
                    if methods
                    else ""
                )
            ) from exc

        if not transport.is_authenticated():
            raise paramiko.AuthenticationException(
                "Platon no autenticó la sesión SSH temporal."
            )

        return []


class PlatonConnection(SSHConnection):
    """
    Platon temporal.

    Directo:
        auth-none Platon -> shell + SFTP Platon.

    Con cambio de usuario:
        auth-none Platon -> PTY -> su - USUARIO

    El SFTP bajo `su` se prueba en una SEGUNDA conexión Platon aislada.
    Un fallo de ese experimento nunca debe tumbar el PTY principal.
    """

    PASSWORD_PROMPTS = (
        "password:",
        "contraseña:",
        "mot de passe:",
    )

    AUTH_FAILURE_MARKERS = (
        "authentication failure",
        "incorrect password",
        "su: authentication",
        "su: incorrect",
        "authentication error",
    )

    def __init__(
        self,
        session,
        jump_password=None,
    ):
        super().__init__(session)

        self.session["auth_mode"] = "platon_none"

        self._su_password_cache = (
            str(jump_password)
            if jump_password is not None
            else None
        )

        # Compatibilidad interna con el nombre usado en 1.2.16/1.2.17.
        self._jump_password_cache = (
            self._su_password_cache
        )

        self._su_sftp_active = False
        self._su_sftp_error = ""
        self._sftp_server_path = ""

    @property
    def auth_mode(self):
        return "platon_none"

    @property
    def jump_enabled(self):
        return bool(
            self.session.get(
                "_platon_jump_enabled",
                False
            )
        )

    @property
    def jump_username(self):
        return str(
            self.session.get(
                "_platon_jump_username",
                ""
            )
        ).strip()

    @property
    def su_sftp_active(self):
        return bool(
            self._su_sftp_active
        )

    @property
    def su_sftp_error(self):
        return str(
            self._su_sftp_error
            or ""
        )

    def _close_handles(
        self,
        emit_state=True,
    ):
        self.connected = False

        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass

        try:
            if self.client:
                self.client.close()
        except Exception:
            pass

        self.sftp = None
        self.client = None
        self._su_sftp_active = False

        if emit_state:
            self.state_changed.emit(
                "Desconectado"
            )

    def _outer_connect_kwargs(self):
        timeout = int(
            self.session.get(
                "_ssh_connect_timeout",
                12
            )
        )

        outer_username = str(
            self.session.get(
                "_platon_outer_username",
                self.session.get(
                    "username",
                    ""
                )
            )
        ).strip()

        return {
            "hostname": self.session["host"],
            "port": int(
                self.session.get(
                    "port",
                    22
                )
            ),
            "username": outer_username,
            "timeout": timeout,
            "banner_timeout": timeout,
            "auth_timeout": int(
                self.session.get(
                    "_ssh_auth_timeout",
                    15
                )
            ),
            "allow_agent": False,
            "look_for_keys": False,
            "compress": bool(
                self.session.get(
                    "_ssh_compression",
                    False
                )
            ),
        }

    def _connect_outer_client(self):
        """
        Abre un cliente Platon auth-none nuevo.

        Para el PTY principal se conserva en self.client.
        Para SFTP aislado el caller pasa ownership a OwnedSFTPClient.
        """
        cli = PlatonSSHClient()

        configure_host_key_client(
            cli,
            KNOWN_HOSTS_FILE
        )

        try:
            cli.connect(
                **self._outer_connect_kwargs()
            )

            transport = (
                cli.get_transport()
            )

            if (
                not transport
                or not transport.is_active()
                or not transport.is_authenticated()
            ):
                raise RuntimeError(
                    "El transporte Platon no quedó autenticado."
                )

            keepalive = int(
                self.session.get(
                    "_ssh_keepalive",
                    20
                )
            )

            if keepalive > 0:
                transport.set_keepalive(
                    keepalive
                )

            return cli

        except Exception:
            try:
                cli.close()
            except Exception:
                pass
            raise

    def _recv_until(
        self,
        channel,
        markers,
        timeout=8.0,
        max_bytes=512_000,
    ):
        markers = tuple(
            str(marker).casefold()
            for marker in markers
        )

        deadline = (
            time.monotonic()
            + max(
                0.2,
                float(timeout)
            )
        )

        raw = bytearray()

        try:
            channel.settimeout(
                0.20
            )
        except Exception:
            pass

        while (
            time.monotonic() < deadline
            and not channel.closed
        ):
            try:
                chunk = channel.recv(
                    65535
                )
            except socket.timeout:
                continue

            if not chunk:
                break

            raw.extend(
                chunk
            )

            if len(raw) > max_bytes:
                del raw[
                    :len(raw) - max_bytes
                ]

            text = bytes(
                raw
            ).decode(
                "utf-8",
                errors="replace"
            ).casefold()

            for marker in markers:
                if marker in text:
                    return (
                        bytes(raw),
                        marker
                    )

        return (
            bytes(raw),
            None
        )

    def _drain_until_quiet(
        self,
        channel,
        total=1.2,
        quiet=0.18,
    ):
        deadline = (
            time.monotonic()
            + max(
                0.2,
                float(total)
            )
        )

        last_data = (
            time.monotonic()
        )

        raw = bytearray()

        try:
            channel.settimeout(
                0.08
            )
        except Exception:
            pass

        while (
            time.monotonic() < deadline
            and not channel.closed
        ):
            try:
                chunk = channel.recv(
                    65535
                )
            except socket.timeout:
                if (
                    raw
                    and (
                        time.monotonic()
                        - last_data
                        >= quiet
                    )
                ):
                    break
                continue

            if not chunk:
                break

            raw.extend(
                chunk
            )
            last_data = (
                time.monotonic()
            )

        return bytes(
            raw
        )

    def _recv_su_identity(
        self,
        channel,
        begin_marker,
        end_marker,
        timeout=10.0,
    ):
        """
        Espera un bloque REAL:

            BEGIN
            usuario
            END

        y NO una simple aparición del marker.

        Esto corrige el bug 1.2.17 donde el eco:
            printf '...MARKER:%s...' "$(id -un)"
        se confundía con la respuesta real.
        """
        deadline = (
            time.monotonic()
            + max(
                0.5,
                float(timeout)
            )
        )

        raw = bytearray()

        pattern = re.compile(
            re.escape(
                begin_marker
            )
            + r"\r?\n"
            + r"([^\r\n]+)"
            + r"\r?\n"
            + re.escape(
                end_marker
            )
        )

        try:
            channel.settimeout(
                0.20
            )
        except Exception:
            pass

        while (
            time.monotonic() < deadline
            and not channel.closed
        ):
            try:
                chunk = channel.recv(
                    65535
                )
            except socket.timeout:
                continue

            if not chunk:
                break

            raw.extend(
                chunk
            )

            if len(raw) > 512_000:
                del raw[
                    :len(raw) - 512_000
                ]

            decoded = bytes(
                raw
            ).decode(
                "utf-8",
                errors="replace"
            )

            lowered = (
                decoded.casefold()
            )

            if any(
                marker in lowered
                for marker
                in self.AUTH_FAILURE_MARKERS
            ):
                raise RuntimeError(
                    "Contraseña incorrecta o `su -` rechazado."
                )

            match = pattern.search(
                decoded
            )

            if match:
                return (
                    decoded,
                    match,
                )

        raise RuntimeError(
            "MobHector no recibió la confirmación completa "
            "del usuario después de su -."
        )

    def _new_outer_shell_channel(
        self,
        width,
        height,
        width_pixels=0,
        height_pixels=0,
    ):
        self.ensure()

        transport = (
            self.get_transport()
        )

        if (
            not transport
            or not transport.is_active()
        ):
            raise RuntimeError(
                "El transporte Platon no está activo."
            )

        channel = transport.open_session(
            timeout=int(
                self.session.get(
                    "_ssh_connect_timeout",
                    12
                )
            )
        )

        channel.set_name(
            "MobHector-Platon-Terminal"
        )

        channel.get_pty(
            term="xterm-256color",
            width=max(
                20,
                int(width)
            ),
            height=max(
                5,
                int(height)
            ),
            width_pixels=max(
                0,
                int(width_pixels)
            ),
            height_pixels=max(
                0,
                int(height_pixels)
            ),
        )

        try:
            channel.update_environment(
                {
                    "COLORTERM": "truecolor",
                    "TERM_PROGRAM": "MobHector",
                    "TERM_PROGRAM_VERSION": APP_VERSION,
                }
            )
        except Exception:
            LOGGER.debug(
                "Platon rechazó variables opcionales de terminal",
                exc_info=True
            )

        channel.invoke_shell()

        try:
            channel.settimeout(
                0.20
            )
        except Exception:
            pass

        return channel

    def _su_shell(
        self,
        channel,
    ):
        username = (
            self.jump_username
        )

        password = (
            self._su_password_cache
        )

        if not username:
            raise RuntimeError(
                "Falta el usuario destino para su -."
            )

        if password is None:
            raise RuntimeError(
                "Falta la contraseña del usuario destino."
            )

        # Consumir banner/prompt del usuario temporal Platon.
        self._drain_until_quiet(
            channel,
            total=1.2,
            quiet=0.18,
        )

        channel.sendall(
            (
                "su - "
                + shlex.quote(
                    username
                )
                + "\r"
            ).encode(
                "utf-8"
            )
        )

        before_password, prompt = (
            self._recv_until(
                channel,
                self.PASSWORD_PROMPTS,
                timeout=8.0,
            )
        )

        if prompt is None:
            lower = (
                before_password.decode(
                    "utf-8",
                    errors="replace"
                ).casefold()
            )

            if any(
                marker in lower
                for marker
                in self.AUTH_FAILURE_MARKERS
            ):
                raise RuntimeError(
                    "El servidor rechazó el cambio "
                    "de usuario con su -."
                )

            raise RuntimeError(
                "No apareció el prompt de contraseña de su -."
            )

        # Secreto sólo al PTY. No log.
        channel.sendall(
            (
                str(password)
                + "\r"
            ).encode(
                "utf-8"
            )
        )

        # Esperar a que su procese contraseña, Last login, motd y prompt.
        post_auth = (
            self._drain_until_quiet(
                channel,
                total=2.2,
                quiet=0.28,
            )
        )

        lower_post = (
            post_auth.decode(
                "utf-8",
                errors="replace"
            ).casefold()
        )

        if any(
            marker in lower_post
            for marker
            in self.AUTH_FAILURE_MARKERS
        ):
            raise RuntimeError(
                "Contraseña incorrecta o `su -` rechazado "
                f"para {username}."
            )

        # Desactivar eco ANTES del chequeo.
        # Aun si no funcionara, el parser exige BEGIN\\nusuario\\nEND,
        # por lo que el texto ecoado del printf no puede dar falso positivo.
        channel.sendall(
            b"stty -echo\r"
        )

        self._drain_until_quiet(
            channel,
            total=0.55,
            quiet=0.12,
        )

        token = (
            uuid.uuid4()
            .hex
            .upper()
        )

        begin_marker = (
            "__MOBHECTOR_SU_BEGIN_"
            + token
            + "__"
        )

        end_marker = (
            "__MOBHECTOR_SU_END_"
            + token
            + "__"
        )

        verify_command = (
            "printf '\\n"
            + begin_marker
            + "\\n'; "
            + "id -un; "
            + "printf '"
            + end_marker
            + "\\n'; "
            + "stty echo"
            + "\r"
        )

        channel.sendall(
            verify_command.encode(
                "utf-8"
            )
        )

        try:
            decoded, match = (
                self._recv_su_identity(
                    channel,
                    begin_marker,
                    end_marker,
                    timeout=10.0,
                )
            )
        except Exception:
            # No dejar la sesión sin echo ante un fallo de validación.
            try:
                channel.sendall(
                    b"stty echo\r"
                )
            except Exception:
                pass
            raise

        actual_user = (
            match.group(1)
            .strip()
        )

        if actual_user != username:
            try:
                channel.sendall(
                    b"stty echo\r"
                )
            except Exception:
                pass

            raise RuntimeError(
                "El `su -` no terminó con el usuario esperado. "
                f"Esperado: {username}; recibido: {actual_user}."
            )

        # Sólo conservar texto posterior al END (normalmente prompt).
        suffix = decoded[
            match.end():
        ]

        suffix = re.sub(
            r"^[\r\n]+",
            "",
            suffix,
            count=1,
        )

        return PrefetchedSSHChannel(
            channel,
            suffix.encode(
                "utf-8",
                errors="replace"
            )
        )

    def _discover_sftp_server_on(
        self,
        client,
    ):
        if self._sftp_server_path:
            return (
                self._sftp_server_path
            )

        transport = (
            client.get_transport()
        )

        if (
            not transport
            or not transport.is_active()
        ):
            raise RuntimeError(
                "El transporte SFTP Platon auxiliar no está activo."
            )

        channel = transport.open_session(
            timeout=int(
                self.session.get(
                    "_ssh_connect_timeout",
                    12
                )
            )
        )

        command = (
            "for p in "
            "/usr/libexec/openssh/sftp-server "
            "/usr/lib/openssh/sftp-server "
            "/usr/lib/ssh/sftp-server "
            "$(command -v sftp-server 2>/dev/null); "
            "do "
            "[ -n \"$p\" ] && [ -x \"$p\" ] && "
            "{ printf '%s\\n' \"$p\"; exit 0; }; "
            "done; exit 1"
        )

        try:
            channel.exec_command(
                command
            )

            chunks = []

            deadline = (
                time.monotonic()
                + 6.0
            )

            while (
                time.monotonic()
                < deadline
            ):
                while (
                    channel.recv_ready()
                ):
                    chunks.append(
                        channel.recv(
                            65535
                        )
                    )

                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                ):
                    break

                time.sleep(
                    0.01
                )

            status = (
                channel.recv_exit_status()
                if channel.exit_status_ready()
                else 1
            )

            output = b"".join(
                chunks
            ).decode(
                "utf-8",
                errors="replace"
            ).strip()

            if (
                status != 0
                or not output
            ):
                raise RuntimeError(
                    "No se encontró sftp-server en el servidor."
                )

            path = (
                output.splitlines()[0]
                .strip()
            )

            if not path.startswith(
                "/"
            ):
                raise RuntimeError(
                    "Ruta sftp-server no válida."
                )

            self._sftp_server_path = (
                path
            )

            return path

        finally:
            try:
                channel.close()
            except Exception:
                pass

    def _open_isolated_direct_sftp(
        self,
    ):
        client = (
            self._connect_outer_client()
        )

        try:
            sftp = (
                client.open_sftp()
            )

            sftp.normalize(
                "."
            )

            return OwnedSFTPClient(
                sftp,
                client
            )

        except Exception:
            try:
                client.close()
            except Exception:
                pass
            raise

    def connect(
        self,
        password=None,
        passphrase=None,
    ):
        del passphrase

        with self.lock:
            if (
                self.jump_enabled
                and password is not None
            ):
                self._su_password_cache = (
                    str(password)
                )
                self._jump_password_cache = (
                    self._su_password_cache
                )

            self._close_handles(
                emit_state=False
            )

            self._su_sftp_error = ""

            self.state_changed.emit(
                "Conectando Platon"
            )

            client = None

            try:
                # MAIN connection: reserved for interactive terminal.
                client = (
                    self._connect_outer_client()
                )

                self.client = client
                self.connected = True

                if self.jump_enabled:
                    # Diseño 1.2.22:
                    # Terminal sí cambia con `su -`.
                    # SFTP conserva la identidad Platon Y su HOME normal.
                    # No se fuerza ninguna ruta del usuario destino.
                    self._su_sftp_active = False
                    self._su_sftp_error = ""

                    sftp = (
                        self._open_isolated_direct_sftp()
                    )

                    self.session[
                        "username"
                    ] = self.jump_username

                else:
                    # Direct legacy behavior remains on main transport.
                    sftp = (
                        client.open_sftp()
                    )
                    self._su_sftp_active = False

                self.sftp = sftp

                resolve_remote_home_and_inbox(
                    self.session,
                    sftp
                )

            except paramiko.BadHostKeyException as exc:
                self._close_handles(
                    emit_state=False
                )

                try:
                    if client:
                        client.close()
                except Exception:
                    pass

                self.state_changed.emit(
                    "Desconectado"
                )

                raise RuntimeError(
                    mismatch_marker(
                        exc
                    )
                ) from exc

            except Exception:
                self._close_handles(
                    emit_state=False
                )

                try:
                    if client:
                        client.close()
                except Exception:
                    pass

                self.state_changed.emit(
                    "Desconectado"
                )
                raise

            self.connected = True

            self.state_changed.emit(
                (
                    "Platon + su conectado"
                    if self.jump_enabled
                    else "Platon conectado"
                )
            )

            return True

    def ensure(self):
        with self.lock:
            if not self.is_alive():
                raise RuntimeError(
                    "La sesión Platon no está conectada."
                )

            sftp_ok = False

            if self.sftp is not None:
                try:
                    channel = (
                        self.sftp.get_channel()
                    )

                    sftp_ok = bool(
                        channel
                        and not channel.closed
                    )
                except Exception:
                    sftp_ok = False

            if not sftp_ok:
                try:
                    if self.sftp is not None:
                        self.sftp.close()
                except Exception:
                    pass

                if self.jump_enabled:
                    self._su_sftp_active = False
                    self.sftp = (
                        self._open_isolated_direct_sftp()
                    )
                else:
                    self.sftp = (
                        self.client.open_sftp()
                    )

            return True

    def open_sftp_session(self):
        with self.lock:
            if not self.is_alive():
                raise RuntimeError(
                    "La sesión Platon no está conectada."
                )

            if self.jump_enabled:
                # Upload/download mantienen la identidad SFTP Platon.
                return (
                    self._open_isolated_direct_sftp()
                )

            return (
                self.get_transport()
                .open_sftp_client()
            )

    def exec(
        self,
        command: str,
        timeout=30,
    ):
        if self.jump_enabled:
            # Remote search uses the portable SFTP backend in this mode.
            raise RuntimeError(
                "Exec directo desactivado en Platon + su; "
                "usar backend SFTP portable."
            )

        return super().exec(
            command,
            timeout=timeout
        )

    def open_shell(
        self,
        width=120,
        height=40,
        width_pixels=0,
        height_pixels=0,
    ):
        channel = (
            self._new_outer_shell_channel(
                width,
                height,
                width_pixels,
                height_pixels,
            )
        )

        if not self.jump_enabled:
            return channel

        try:
            return (
                self._su_shell(
                    channel
                )
            )

        except Exception:
            try:
                channel.close()
            except Exception:
                pass
            raise

    def close(
        self,
        clear_secret=True,
    ):
        with self.lock:
            self._close_handles(
                emit_state=True
            )

            if clear_secret:
                self._su_password_cache = None
                self._jump_password_cache = None
                self._password_cache = None
                self._passphrase_cache = None


# ============================================================
# Windows Local Shell / ConPTY
# ============================================================

class _ConPTYCoord(ctypes.Structure):
    _fields_ = [
        ("X", ctypes.c_short),
        ("Y", ctypes.c_short),
    ]


class _ConPTYStartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ConPTYStartupInfoExW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _ConPTYStartupInfoW),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class _ConPTYProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class LocalConPTYChannel:
    """
    Adaptador ConPTY con la interfaz mínima que TerminalWidget/TerminalReader
    ya usan con un canal Paramiko:
      recv / recv_ready / sendall / resize_pty / close / closed

    De esta forma PowerShell/CMD utiliza el MISMO xterm.js de MobHector.
    """
    PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    WAIT_TIMEOUT = 258
    ERROR_BROKEN_PIPE = 109
    ERROR_NO_DATA = 232

    _kernel32 = None
    _api_ready = False

    @classmethod
    def _api(cls):
        if os.name != "nt":
            raise RuntimeError(
                "ConPTY sólo está disponible en Windows."
            )

        if cls._kernel32 is not None and cls._api_ready:
            return cls._kernel32

        try:
            kernel32 = ctypes.WinDLL(
                "kernel32",
                use_last_error=True
            )
        except Exception as exc:
            raise RuntimeError(
                "No se pudo cargar kernel32 para ConPTY."
            ) from exc

        required = (
            "CreatePseudoConsole",
            "ResizePseudoConsole",
            "ClosePseudoConsole",
            "CreatePipe",
            "PeekNamedPipe",
            "ReadFile",
            "WriteFile",
            "CloseHandle",
            "InitializeProcThreadAttributeList",
            "UpdateProcThreadAttribute",
            "DeleteProcThreadAttributeList",
            "CreateProcessW",
            "WaitForSingleObject",
            "TerminateProcess",
        )

        missing = [
            name for name in required
            if not hasattr(kernel32, name)
        ]
        if missing:
            raise RuntimeError(
                "Esta versión de Windows no expone ConPTY. "
                "Se requiere Windows 10 1809 o posterior. "
                "Faltan: " + ", ".join(missing)
            )

        HANDLE_P = ctypes.POINTER(wintypes.HANDLE)
        DWORD_P = ctypes.POINTER(wintypes.DWORD)
        SIZE_T_P = ctypes.POINTER(ctypes.c_size_t)

        kernel32.CreatePipe.argtypes = [
            HANDLE_P, HANDLE_P, wintypes.LPVOID, wintypes.DWORD
        ]
        kernel32.CreatePipe.restype = wintypes.BOOL

        kernel32.CreatePseudoConsole.argtypes = [
            _ConPTYCoord,
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.DWORD,
            HANDLE_P,
        ]
        kernel32.CreatePseudoConsole.restype = ctypes.c_long

        kernel32.ResizePseudoConsole.argtypes = [
            wintypes.HANDLE,
            _ConPTYCoord,
        ]
        kernel32.ResizePseudoConsole.restype = ctypes.c_long

        kernel32.ClosePseudoConsole.argtypes = [
            wintypes.HANDLE
        ]
        kernel32.ClosePseudoConsole.restype = None

        kernel32.PeekNamedPipe.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            DWORD_P,
            DWORD_P,
            DWORD_P,
        ]
        kernel32.PeekNamedPipe.restype = wintypes.BOOL

        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            DWORD_P,
            wintypes.LPVOID,
        ]
        kernel32.ReadFile.restype = wintypes.BOOL

        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            DWORD_P,
            wintypes.LPVOID,
        ]
        kernel32.WriteFile.restype = wintypes.BOOL

        kernel32.CloseHandle.argtypes = [
            wintypes.HANDLE
        ]
        kernel32.CloseHandle.restype = wintypes.BOOL

        kernel32.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            SIZE_T_P,
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL

        kernel32.UpdateProcThreadAttribute.argtypes = [
            wintypes.LPVOID,
            ctypes.c_size_t,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            SIZE_T_P,
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL

        kernel32.DeleteProcThreadAttributeList.argtypes = [
            wintypes.LPVOID
        ]
        kernel32.DeleteProcThreadAttributeList.restype = None

        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            wintypes.LPVOID,
            ctypes.POINTER(_ConPTYProcessInformation),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL

        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD

        kernel32.TerminateProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        kernel32.TerminateProcess.restype = wintypes.BOOL

        cls._kernel32 = kernel32
        cls._api_ready = True
        return kernel32

    @classmethod
    def supported(cls):
        if os.name != "nt":
            return False
        try:
            cls._api()
            return True
        except Exception:
            return False

    @staticmethod
    def _check_bool(ok, label):
        if ok:
            return
        code = ctypes.get_last_error()
        raise OSError(
            code,
            f"{label} falló (WinError {code})"
        )

    @staticmethod
    def _check_hresult(hr, label):
        # HRESULT >= 0 = éxito.
        if int(hr) >= 0:
            return
        unsigned = ctypes.c_uint32(int(hr)).value
        raise OSError(
            unsigned,
            f"{label} falló (HRESULT 0x{unsigned:08X})"
        )

    def __init__(
        self,
        command,
        cwd=None,
        width=120,
        height=40,
        timeout=0.2,
    ):
        self.command = list(command)
        self.cwd = str(cwd or Path.home())
        self.timeout = max(0.05, float(timeout))
        self._closed = False
        self._lock = threading.RLock()
        self._hpc = wintypes.HANDLE()
        self._input_write = wintypes.HANDLE()
        self._output_read = wintypes.HANDLE()
        self._process_handle = wintypes.HANDLE()
        self.process_id = 0

        self._start(
            max(20, int(width)),
            max(5, int(height)),
        )

    @property
    def closed(self):
        return bool(self._closed)

    def _safe_close_handle(self, handle):
        if not handle:
            return
        try:
            value = getattr(handle, "value", handle)
            if value:
                self._api().CloseHandle(
                    wintypes.HANDLE(value)
                )
        except Exception:
            pass

    def _start(self, width, height):
        kernel32 = self._api()

        input_read = wintypes.HANDLE()
        input_write = wintypes.HANDLE()
        output_read = wintypes.HANDLE()
        output_write = wintypes.HANDLE()

        self._check_bool(
            kernel32.CreatePipe(
                ctypes.byref(input_read),
                ctypes.byref(input_write),
                None,
                0,
            ),
            "CreatePipe(input)"
        )

        try:
            self._check_bool(
                kernel32.CreatePipe(
                    ctypes.byref(output_read),
                    ctypes.byref(output_write),
                    None,
                    0,
                ),
                "CreatePipe(output)"
            )
        except Exception:
            self._safe_close_handle(input_read)
            self._safe_close_handle(input_write)
            raise

        hpc = wintypes.HANDLE()

        try:
            hr = kernel32.CreatePseudoConsole(
                _ConPTYCoord(width, height),
                input_read,
                output_write,
                0,
                ctypes.byref(hpc),
            )
            self._check_hresult(
                hr,
                "CreatePseudoConsole"
            )
        except Exception:
            self._safe_close_handle(input_read)
            self._safe_close_handle(input_write)
            self._safe_close_handle(output_read)
            self._safe_close_handle(output_write)
            raise

        # ConPTY ya conserva sus extremos internos.
        self._safe_close_handle(input_read)
        self._safe_close_handle(output_write)

        attribute_size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(
            None,
            1,
            0,
            ctypes.byref(attribute_size),
        )

        attribute_buffer = ctypes.create_string_buffer(
            max(1, int(attribute_size.value))
        )
        attribute_list = ctypes.cast(
            attribute_buffer,
            wintypes.LPVOID
        )

        try:
            self._check_bool(
                kernel32.InitializeProcThreadAttributeList(
                    attribute_list,
                    1,
                    0,
                    ctypes.byref(attribute_size),
                ),
                "InitializeProcThreadAttributeList"
            )

            self._check_bool(
                kernel32.UpdateProcThreadAttribute(
                    attribute_list,
                    0,
                    self.PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    ctypes.c_void_p(hpc.value),
                    ctypes.sizeof(wintypes.HANDLE),
                    None,
                    None,
                ),
                "UpdateProcThreadAttribute(ConPTY)"
            )

            startup = _ConPTYStartupInfoExW()
            startup.StartupInfo.cb = ctypes.sizeof(
                _ConPTYStartupInfoExW
            )
            startup.lpAttributeList = attribute_list

            process_info = _ConPTYProcessInformation()

            command_line = subprocess.list2cmdline(
                self.command
            )
            mutable_command = ctypes.create_unicode_buffer(
                command_line
            )

            flags = (
                self.EXTENDED_STARTUPINFO_PRESENT
                | self.CREATE_UNICODE_ENVIRONMENT
            )

            self._check_bool(
                kernel32.CreateProcessW(
                    None,
                    mutable_command,
                    None,
                    None,
                    False,
                    flags,
                    None,
                    self.cwd,
                    ctypes.byref(startup),
                    ctypes.byref(process_info),
                ),
                "CreateProcessW(Local Shell)"
            )

        except Exception:
            try:
                kernel32.ClosePseudoConsole(hpc)
            except Exception:
                pass
            self._safe_close_handle(input_write)
            self._safe_close_handle(output_read)
            raise

        finally:
            try:
                kernel32.DeleteProcThreadAttributeList(
                    attribute_list
                )
            except Exception:
                pass

        self._safe_close_handle(process_info.hThread)

        self._hpc = hpc
        self._input_write = input_write
        self._output_read = output_read
        self._process_handle = process_info.hProcess
        self.process_id = int(process_info.dwProcessId)
        self._closed = False

    def process_alive(self):
        if self._closed or not self._process_handle:
            return False
        try:
            result = self._api().WaitForSingleObject(
                self._process_handle,
                0,
            )
            return result == self.WAIT_TIMEOUT
        except Exception:
            return False

    def _available_bytes(self):
        if self._closed or not self._output_read:
            return 0

        available = wintypes.DWORD(0)
        ok = self._api().PeekNamedPipe(
            self._output_read,
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        )
        if not ok:
            code = ctypes.get_last_error()
            if code in (
                self.ERROR_BROKEN_PIPE,
                self.ERROR_NO_DATA,
            ):
                return 0
            raise OSError(
                code,
                f"PeekNamedPipe falló (WinError {code})"
            )

        return int(available.value)

    def recv_ready(self):
        try:
            return self._available_bytes() > 0
        except Exception:
            return False

    def recv(self, size):
        size = max(1, min(1024 * 1024, int(size)))
        deadline = time.monotonic() + self.timeout

        while not self._closed:
            try:
                available = self._available_bytes()
            except OSError as exc:
                if exc.errno in (
                    self.ERROR_BROKEN_PIPE,
                    self.ERROR_NO_DATA,
                ):
                    return b""
                raise

            if available > 0:
                count = min(size, available)
                buffer = ctypes.create_string_buffer(count)
                read = wintypes.DWORD(0)

                ok = self._api().ReadFile(
                    self._output_read,
                    buffer,
                    count,
                    ctypes.byref(read),
                    None,
                )

                if not ok:
                    code = ctypes.get_last_error()
                    if code in (
                        self.ERROR_BROKEN_PIPE,
                        self.ERROR_NO_DATA,
                    ):
                        return b""
                    raise OSError(
                        code,
                        f"ReadFile(ConPTY) falló "
                        f"(WinError {code})"
                    )

                return buffer.raw[:int(read.value)]

            if not self.process_alive():
                return b""

            if time.monotonic() >= deadline:
                raise socket.timeout()

            time.sleep(0.01)

        return b""

    def sendall(self, data):
        if self._closed:
            raise OSError(
                "La terminal local ya está cerrada."
            )

        raw = bytes(data)
        offset = 0

        with self._lock:
            while offset < len(raw):
                chunk = raw[offset:offset + 65536]
                written = wintypes.DWORD(0)
                cbuf = ctypes.create_string_buffer(
                    chunk,
                    len(chunk)
                )

                ok = self._api().WriteFile(
                    self._input_write,
                    cbuf,
                    len(chunk),
                    ctypes.byref(written),
                    None,
                )

                if not ok:
                    code = ctypes.get_last_error()
                    if code in (
                        self.ERROR_BROKEN_PIPE,
                        self.ERROR_NO_DATA,
                    ):
                        self._closed = True
                    raise OSError(
                        code,
                        f"WriteFile(ConPTY) falló "
                        f"(WinError {code})"
                    )

                if int(written.value) <= 0:
                    raise OSError(
                        "ConPTY no aceptó datos de entrada."
                    )

                offset += int(written.value)

    def resize_pty(
        self,
        width=120,
        height=40,
        width_pixels=0,
        height_pixels=0,
    ):
        if self._closed or not self._hpc:
            return

        width = max(20, min(1000, int(width)))
        height = max(5, min(500, int(height)))

        hr = self._api().ResizePseudoConsole(
            self._hpc,
            _ConPTYCoord(width, height),
        )
        self._check_hresult(
            hr,
            "ResizePseudoConsole"
        )

    def close(self):
        with self._lock:
            if self._closed:
                return

            self._closed = True
            kernel32 = None

            try:
                kernel32 = self._api()
            except Exception:
                pass

            # Cerrar entrada primero equivale a EOF para el shell.
            self._safe_close_handle(self._input_write)
            self._input_write = wintypes.HANDLE()

            if kernel32 and self._hpc:
                try:
                    kernel32.ClosePseudoConsole(
                        self._hpc
                    )
                except Exception:
                    pass
            self._hpc = wintypes.HANDLE()

            if kernel32 and self._process_handle:
                try:
                    result = kernel32.WaitForSingleObject(
                        self._process_handle,
                        250,
                    )
                    if result == self.WAIT_TIMEOUT:
                        kernel32.TerminateProcess(
                            self._process_handle,
                            0,
                        )
                except Exception:
                    pass

            self._safe_close_handle(self._output_read)
            self._output_read = wintypes.HANDLE()

            self._safe_close_handle(
                self._process_handle
            )
            self._process_handle = wintypes.HANDLE()


class LocalShellConnection(QObject):
    """Conexión local Windows que reutiliza TerminalWidget/xterm.js."""
    state_changed = Signal(str)
    is_local_shell = True

    def __init__(self, shell_kind="powershell"):
        super().__init__()
        self.shell_kind = str(
            shell_kind or "powershell"
        ).strip().lower()
        self.channel = None
        self.lock = threading.RLock()

        self.shell_exe, self.shell_args, self.display_name = (
            self._resolve_shell()
        )

        self.session = {
            "name": self.display_name,
            "host": "LOCAL",
            "username": (
                os.environ.get("USERNAME")
                or Path.home().name
                or "Windows"
            ),
            "port": 0,
            "_auto_focus_terminal": True,
        }

    def _resolve_shell(self):
        if os.name != "nt":
            raise RuntimeError(
                "Local Shell integrado está disponible sólo en Windows."
            )

        if self.shell_kind == "cmd":
            exe = (
                os.environ.get("COMSPEC")
                or shutil.which("cmd.exe")
                or "cmd.exe"
            )
            return exe, [], "CMD"

        if self.shell_kind == "wsl":
            exe = shutil.which("wsl.exe")
            if not exe:
                system_root = os.environ.get("SystemRoot", r"C:\Windows")
                candidate = Path(system_root) / "System32" / "wsl.exe"
                if candidate.exists():
                    exe = str(candidate)
            if not exe:
                raise RuntimeError(
                    "WSL no está instalado o wsl.exe no está disponible en PATH."
                )
            return exe, [], "WSL"

        if self.shell_kind in ("gitbash", "git-bash", "git"):
            candidates = []
            found = shutil.which("bash.exe")
            if found:
                candidates.append(Path(found))
            for base in (
                os.environ.get("ProgramFiles", ""),
                os.environ.get("ProgramFiles(x86)", ""),
                os.environ.get("LOCALAPPDATA", ""),
            ):
                if not base:
                    continue
                root = Path(base)
                candidates.extend([
                    root / "Git" / "bin" / "bash.exe",
                    root / "Programs" / "Git" / "bin" / "bash.exe",
                ])
            exe = next((str(c) for c in candidates if c.exists()), "")
            if not exe:
                raise RuntimeError(
                    "Git Bash no fue encontrado. Instala Git for Windows o agrega bash.exe al PATH."
                )
            return exe, ["--login", "-i"], "Git Bash"

        exe = (
            shutil.which("pwsh.exe")
            or shutil.which("powershell.exe")
            or "powershell.exe"
        )

        if Path(exe).name.casefold() == "pwsh.exe":
            return exe, ["-NoLogo"], "PowerShell 7"

        return exe, ["-NoLogo"], "Windows PowerShell"

    def get_transport(self):
        # TerminalReader acepta transport=None.
        return None

    def is_alive(self):
        return bool(
            self.channel
            and not self.channel.closed
            and self.channel.process_alive()
        )

    def open_shell(
        self,
        width=120,
        height=40,
        width_pixels=0,
        height_pixels=0,
    ):
        with self.lock:
            if self.channel is not None:
                try:
                    self.channel.close()
                except Exception:
                    pass

            self.state_changed.emit("Abriendo terminal local")

            command = [
                self.shell_exe,
                *self.shell_args,
            ]

            self.channel = LocalConPTYChannel(
                command,
                cwd=Path.home(),
                width=width,
                height=height,
                timeout=0.2,
            )

            self.state_changed.emit("Conectado")
            return self.channel

    def close(self, clear_secret=True):
        with self.lock:
            channel = self.channel
            self.channel = None

            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    LOGGER.debug(
                        "Error cerrando ConPTY",
                        exc_info=True
                    )

            self.state_changed.emit("Desconectado")


# ============================================================
# ANSI rich terminal
# ============================================================

class TerminalReader(QThread):
    data = Signal(str)
    closed = Signal()
    failed = Signal(str)

    def __init__(self, channel, transport=None):
        super().__init__()
        self.channel = channel
        self.transport = transport
        self.running = True
        self._flow = threading.Condition()
        self._inflight = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )

    def run(self):
        """
        Lectura bloqueante con timeout corto.

        La versión anterior consultaba recv_ready() cada ~18 ms, lo que
        despertaba Python ~55 veces/s por terminal incluso sin tráfico.
        recv() bloqueante usa el timeout del canal (0.2 s), reduce CPU y
        mantiene la misma respuesta interactiva. Cuando llega una ráfaga,
        se drena hasta 512 KiB antes de emitir una sola señal Qt.
        """
        next_transport_check = 0.0

        try:
            while self.running and not self.channel.closed:
                with self._flow:
                    self._flow.wait_for(lambda: not self.running or self._inflight < 1024 * 1024)
                if not self.running:
                    break
                now = time.monotonic()
                if now >= next_transport_check:
                    next_transport_check = now + 1.0
                    if (
                        self.transport is not None
                        and not self.transport.is_active()
                    ):
                        self.failed.emit(
                            "Conexión SSH perdida: transporte inactivo"
                        )
                        break

                try:
                    first = self.channel.recv(65535)
                    if not first:
                        break

                    chunks = [first]
                    budget = 512 * 1024 - len(first)

                    while (
                        self.running
                        and budget > 0
                        and not self.channel.closed
                        and self.channel.recv_ready()
                    ):
                        raw = self.channel.recv(min(65535, budget))
                        if not raw:
                            break
                        chunks.append(raw)
                        budget -= len(raw)

                    decoded = self._decoder.decode(
                        b"".join(chunks),
                        final=False
                    )
                    if decoded:
                        with self._flow:
                            self._inflight += len(decoded.encode("utf-16-le")) // 2
                        self.data.emit(decoded)

                except socket.timeout:
                    continue
                except Exception as exc:
                    if self.running:
                        self.failed.emit(str(exc))
                    break
        finally:
            try:
                tail = self._decoder.decode(b"", final=True)
                if tail:
                    self.data.emit(tail)
            except Exception:
                pass
            self.closed.emit()

    def release_output(self, count):
        with self._flow:
            self._inflight = max(0, self._inflight - count)
            self._flow.notify_all()

    def stop(self):
        self.running = False
        with self._flow:
            self._flow.notify_all()


class XtermBridge(QObject):
    """Puente WebChannel xterm.js <-> PTY Paramiko."""
    output = Signal(str)
    connected = Signal()
    disconnected = Signal(str)
    zoom_request = Signal(int)
    ready_signal = Signal()
    user_input = Signal(str)
    paste_input = Signal(str)
    connection_action = Signal(str)
    directory_changed = Signal(str)
    output_consumed = Signal(int)
    input_warning = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channel = None
        self._ready = False
        self._pending_output = []
        self._pending_chars = 0
        self._send_lock = threading.Lock()
        self._writer = None
        self._disconnected_mode = False
        self._last_paste_text = None
        self._last_paste_monotonic = 0.0

    def set_channel(self, channel):
        self.clear_channel()
        self.channel = channel
        self._writer = AsyncChannelWriter(channel, self.disconnected.emit)
        self._disconnected_mode = False
        self.connected.emit()

    def clear_channel(self):
        if self._writer is not None:
            self._writer.stop()
            self._writer = None
        self.channel = None

    @Slot(int)
    def outputAck(self, count):
        self.output_consumed.emit(max(0, count))

    def set_disconnected_mode(self, enabled):
        self._disconnected_mode = bool(enabled)

    @Slot()
    def ready(self):
        self._ready = True
        self.ready_signal.emit()
        if self._pending_output:
            pending = "".join(self._pending_output)
            self._pending_output.clear()
            self._pending_chars = 0
            self.output.emit(pending)

    def write_output(self, text: str):
        if self._ready:
            self.output.emit(text)
        else:
            self._pending_output.append(text)
            self._pending_chars += len(text)
            if self._pending_chars > 2_000_000:
                self._pending_output = self._pending_output[-100:]
                self._pending_chars = sum(
                    len(chunk) for chunk in self._pending_output
                )

    def send_raw(self, data: str, announce=False):
        """Envía al PTY. Broadcast MultiExec nunca se reemite."""
        ch = self.channel
        if not ch or ch.closed:
            return False
        try:
            raw = data.encode("utf-8", errors="surrogatepass")
            if self._writer is None or not self._writer.submit(raw):
                self.input_warning.emit("Cola de teclado llena: espera antes de volver a pegar.")
                return False
            if announce:
                self.user_input.emit(data)
            return True
        except Exception as exc:
            self.disconnected.emit(str(exc))
            return False

    @Slot(str)
    def localInput(self, data: str):
        """Entrada local que no se replica a MultiExec."""
        if self._disconnected_mode:
            return
        self.send_raw(data, announce=False)

    @Slot(str)
    def binaryInput(self, data: str):
        """
        Reportes binarios de xterm.js (incluido mouse legacy).

        Se reenvían byte-a-byte al PTY y nunca se anuncian a MultiExec.
        """
        if self._disconnected_mode:
            return

        ch = self.channel
        if not ch or ch.closed:
            return

        try:
            raw = bytes((ord(char) & 0xFF) for char in str(data))
            if self._writer is not None:
                self._writer.submit(raw)
        except Exception as exc:
            self.disconnected.emit(str(exc))

    @Slot(str)
    def input(self, data: str):
        # Cuando SSH termina, R/Q son controles locales y jamás se
        # propagan a MultiExec ni al servidor.
        if self._disconnected_mode:
            if data in ("r", "R"):
                self.connection_action.emit("reconnect")
            elif data in ("q", "Q"):
                self.connection_action.emit("close")
            return
        self.send_raw(data, announce=True)

    @Slot(str)
    def reportDirectory(self, path: str):
        """Recibe OSC 7 ya parseado por xterm.js; nunca ejecuta comandos."""
        value = str(path or "").strip()
        if value.startswith("/") and "\x00" not in value:
            self.directory_changed.emit(value[:4096])

    @Slot(int, int, int, int)
    def resize(
        self,
        cols: int,
        rows: int,
        width_pixels: int = 0,
        height_pixels: int = 0
    ):
        ch = self.channel
        if not ch or ch.closed:
            return

        try:
            cols = max(20, min(1000, int(cols)))
            rows = max(5, min(500, int(rows)))
            width_pixels = max(
                0,
                min(20000, int(width_pixels or 0))
            )
            height_pixels = max(
                0,
                min(20000, int(height_pixels or 0))
            )

            ch.resize_pty(
                width=cols,
                height=rows,
                width_pixels=width_pixels,
                height_pixels=height_pixels
            )
        except Exception:
            LOGGER.debug(
                "resize_pty rechazado",
                exc_info=True
            )

    @Slot(int)
    def requestZoom(self, delta: int):
        self.zoom_request.emit(1 if delta > 0 else -1)

    @Slot(str)
    def copySelection(self, text: str):
        """Copia directamente al portapapeles de Windows/Qt."""
        if text:
            QApplication.clipboard().setText(str(text))

    @Slot(bool)
    def pasteClipboard(self, bracketed: bool = False):
        """Pega respetando bracketed paste cuando Vim/TUI lo solicita."""
        text = QApplication.clipboard().text()
        if not text:
            return

        now = time.monotonic()
        if (
            text == self._last_paste_text
            and (now - self._last_paste_monotonic) < 0.060
        ):
            LOGGER.debug("Pegado duplicado descartado")
            return

        self._last_paste_text = text
        self._last_paste_monotonic = now

        if self._disconnected_mode:
            return

        # Reject embedded escape sequences that can terminate bracketed paste.
        if len(text.encode("utf-8")) > 1024 * 1024:
            self.input_warning.emit("El pegado está limitado a 1 MiB; usa SFTP para archivos grandes.")
            return
        dangerous = any(ord(c) < 32 and c not in "\r\n\t" for c in text)
        multiline = "\n" in text or "\r" in text
        if dangerous or (multiline and not bracketed):
            dialog = QMessageBox(self.parent())
            dialog.setWindowTitle("Revisar pegado")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText("El texto contiene controles o varias líneas que podrían ejecutar comandos. ¿Pegar?")
            dialog.setDetailedText(text[:6000])
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if dialog.exec() != QMessageBox.StandardButton.Yes:
                return
        text = "".join(c for c in text if ord(c) >= 32 or c in "\r\n\t")
        # Emular pegado de terminal: newline del clipboard -> Enter en PTY.
        terminal_text = (
            str(text)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "\r")
        )

        payload = terminal_text
        if bool(bracketed):
            payload = "\x1b[200~" + terminal_text + "\x1b[201~"

        if self.send_raw(payload, announce=False):
            # MultiExec recibe sólo contenido, nunca wrappers bracketed.
            self.paste_input.emit(terminal_text)



class TerminalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_main_frame:
            return False
        terminal = (Path(__file__).resolve().parent / "assets" / "terminal.html").resolve()
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() == terminal

    def createWindow(self, window_type):
        return None


class TerminalWebView(QWebEngineView):
    """
    WebView especializado para atajos de historial local.

    Shift+PageUp/PageDown y Ctrl+Shift+Home/End se consumen aquí,
    antes de Chromium/xterm, para que nunca lleguen al PTY.
    """
    history_shortcut = Signal(str)

    @staticmethod
    def _history_action(event):
        modifiers = event.modifiers()
        key = event.key()

        shift = bool(
            modifiers & Qt.KeyboardModifier.ShiftModifier
        )
        ctrl = bool(
            modifiers & Qt.KeyboardModifier.ControlModifier
        )
        alt = bool(
            modifiers & Qt.KeyboardModifier.AltModifier
        )
        meta = bool(
            modifiers & Qt.KeyboardModifier.MetaModifier
        )

        if shift and not ctrl and not alt and not meta:
            if key == Qt.Key.Key_PageUp:
                return "pageup"
            if key == Qt.Key.Key_PageDown:
                return "pagedown"

        if shift and ctrl and not alt and not meta:
            if key == Qt.Key.Key_Home:
                return "top"
            if key == Qt.Key.Key_End:
                return "bottom"

        return ""

    def keyPressEvent(self, event):
        action = self._history_action(event)
        if action:
            event.accept()
            self.history_shortcut.emit(action)
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        action = self._history_action(event)
        if action:
            event.accept()
            return

        super().keyReleaseEvent(event)

class TerminalWidget(QWidget):
    """Terminal xterm.js con estado de reconexión R/Q."""
    status_message = Signal(str)
    zoom_changed = Signal(int)
    user_input = Signal(str)
    paste_input = Signal(str)
    connection_lost = Signal(str)
    reconnect_requested = Signal()
    close_requested = Signal()
    directory_changed = Signal(str)

    def __init__(
        self,
        connection: SSHConnection,
        initial_zoom=100,
        clipboard_preferences=None,
        terminal_preferences=None,
        parent=None
    ):
        super().__init__(parent)
        self.connection = connection
        self.is_local_shell = bool(
            getattr(connection, "is_local_shell", False)
        )
        self.channel = None
        self.reader = None
        self.zoom_percent = int(initial_zoom)
        self._page_loaded = False
        self._shell_started = False
        self.visual_mode = "dark"

        prefs = dict(clipboard_preferences or {})
        self.clipboard_preferences = {
            "auto_copy_selection": bool(
                prefs.get("auto_copy_selection", True)
            ),
            "ctrl_v_paste": bool(
                prefs.get("ctrl_v_paste", True)
            ),
            "right_click_paste": bool(
                prefs.get("right_click_paste", True)
            ),
        }

        tprefs = dict(terminal_preferences or {})
        self.terminal_preferences = {
            "font_family": str(
                tprefs.get("font_family", "Cascadia Mono")
            ),
            "font_size": int(tprefs.get("font_size", 14)),
            "cursor_style": str(tprefs.get("cursor_style", "block")),
            "cursor_blink": bool(tprefs.get("cursor_blink", True)),
            "scrollback": int(tprefs.get("scrollback", 500000)),
            "history_sticky": bool(tprefs.get("history_sticky", True)),
            "protect_scrollback": bool(
                tprefs.get("protect_scrollback", True)
            ),
            "selection_autoscroll": bool(
                tprefs.get("selection_autoscroll", True)
            ),
            "line_height": int(tprefs.get("line_height", 108)),
            "bold_bright": bool(tprefs.get("bold_bright", True)),
            "click_to_cursor": bool(tprefs.get("click_to_cursor", True)),
            "tui_native_mouse": bool(tprefs.get("tui_native_mouse", True)),
            "tui_arrow_fallback": bool(
                tprefs.get("tui_arrow_fallback", True)
            ),
            "middle_click_paste": bool(tprefs.get("middle_click_paste", False)),
            "bell_style": str(tprefs.get("bell_style", "none")),
            "word_mode": str(tprefs.get("word_mode", "unix")),
            "show_scrollbar": bool(tprefs.get("show_scrollbar", True)),
        }

        self._intentional_close = False
        self._disconnect_notified = False
        self._reader_error = ""
        self._reconnecting = False

        # Transcript manual de sesión (SecureCRT/Termius style).
        self._transcript_handle = None
        self._transcript_path = None

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_terminal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = TerminalWebView(self)
        self.view.setPage(TerminalPage(self.view))
        self.view.setObjectName("xtermView")
        self.view.history_shortcut.connect(
            self._handle_history_shortcut
        )
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.view.page().setBackgroundColor(QColor("#050607"))

        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )

        self.bridge = XtermBridge(self)
        self.bridge.input_warning.connect(self.status_message.emit)
        self.bridge.output_consumed.connect(self._ack_output)
        self.bridge.zoom_request.connect(self._zoom_from_wheel)
        self.bridge.disconnected.connect(self._on_bridge_disconnected)
        self.bridge.ready_signal.connect(self._bridge_ready)
        self.bridge.user_input.connect(self.user_input.emit)
        self.bridge.paste_input.connect(self.paste_input.emit)
        self.bridge.connection_action.connect(self._connection_action)
        self.bridge.directory_changed.connect(self.directory_changed.emit)

        self.web_channel = QWebChannel(self.view.page())
        self.web_channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.web_channel)

        terminal_html = Path(__file__).resolve().parent / "assets" / "terminal.html"
        if not terminal_html.exists():
            fallback = (
                "<html><body style='background:#050607;color:#ff6b6b;"
                "font-family:monospace;padding:20px'>"
                "<h2>MobHector</h2>"
                "<p>No se encontró assets/terminal.html.</p>"
                "</body></html>"
            )
            self.view.setHtml(fallback)
        else:
            self.view.load(QUrl.fromLocalFile(str(terminal_html)))

        self.view.loadFinished.connect(self._load_finished)
        layout.addWidget(self.view, 1)

    def _load_finished(self, ok: bool):
        self._page_loaded = bool(ok)
        if not ok:
            self.status_message.emit("No se pudo cargar xterm.js")
            return
        self._apply_zoom_js()
        self._apply_visual_mode_js()
        self._apply_clipboard_preferences_js()
        self._apply_terminal_preferences_js()

    def _bridge_ready(self):
        self._apply_zoom_js()
        self._apply_visual_mode_js()
        self._apply_clipboard_preferences_js()
        self._apply_terminal_preferences_js()
        if self.channel and not self.channel.closed:
            self.bridge.set_channel(self.channel)

    def start(self):
        if self._shell_started:
            return
        self._shell_started = True
        self._intentional_close = False
        self._disconnect_notified = False
        self._reader_error = ""
        self._reconnecting = False
        self.bridge.set_disconnected_mode(False)
        try:
            # Se inicia con un tamaño conservador. xterm.js enviará las
            # dimensiones reales inmediatamente mediante resize_pty().
            self.channel = self.connection.open_shell(
                width=120,
                height=40
            )
            self.bridge.set_channel(self.channel)

            self.reader = TerminalReader(
                self.channel,
                self.connection.get_transport()
            )
            self.reader.data.connect(self._on_ssh_data)
            self.reader.failed.connect(self._reader_failed)
            self.reader.closed.connect(self._reader_closed)
            self.reader.start()

            QTimer.singleShot(250, self.fit_terminal)
            if bool(
                self.connection.session.get("_auto_focus_terminal", True)
            ):
                QTimer.singleShot(600, self.focus_terminal)
        except Exception as exc:
            self._shell_started = False
            self.notify_connection_lost(str(exc))

    @Slot(int)
    def _ack_output(self, count):
        if self.reader is not None:
            self.reader.release_output(count)

    @Slot(str)
    def _on_ssh_data(self, data: str):
        self.bridge.write_output(data)
        if self._transcript_handle is not None:
            try:
                self._transcript_handle.write(str(data))
                self._transcript_handle.flush()
            except Exception:
                LOGGER.exception("No se pudo escribir transcript de terminal")
                self.stop_transcript()

    def start_transcript(self, label="session"):
        if self._transcript_handle is not None:
            return self._transcript_path
        target_dir = LOG_DIR / "Sessions"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label or "session")).strip("._")
        safe = safe[:80] or "session"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = target_dir / f"{stamp}_{safe}.log"
        self._transcript_handle = open(path, "a", encoding="utf-8", errors="replace", newline="")
        self._transcript_path = path
        self._transcript_handle.write(
            f"# MobHector {APP_VERSION} transcript\n"
            f"# Inicio: {datetime.now().isoformat(timespec='seconds')}\n\n"
        )
        self._transcript_handle.flush()
        return path

    def stop_transcript(self):
        handle = self._transcript_handle
        path = self._transcript_path
        self._transcript_handle = None
        self._transcript_path = None
        if handle is not None:
            try:
                handle.write(f"\n# Fin: {datetime.now().isoformat(timespec='seconds')}\n")
                handle.close()
            except Exception:
                LOGGER.debug("No se pudo cerrar transcript", exc_info=True)
        return path

    def transcript_active(self):
        return self._transcript_handle is not None

    def search_text(self, query, backwards=False, case_sensitive=False):
        query = str(query or "")
        if not query or not self._page_loaded:
            return False
        js = (
            "window.mobhectorSearchTerminal && "
            "window.mobhectorSearchTerminal("
            + json.dumps(query) + ","
            + ("-1" if backwards else "1") + ","
            + ("true" if case_sensitive else "false")
            + ");"
        )
        self.view.page().runJavaScript(js)
        return True

    @Slot(str)
    def _reader_failed(self, reason: str):
        self._reader_error = compact_error(reason)
        self.notify_connection_lost(self._reader_error)

    @Slot()
    def _reader_closed(self):
        if self._intentional_close or self._reconnecting:
            return
        reason = self._reader_error or (
            "La terminal local finalizó."
            if self.is_local_shell
            else "La terminal SSH remota finalizó."
        )
        self.notify_connection_lost(reason)

    @Slot(str)
    def _on_bridge_disconnected(self, reason: str):
        if self._intentional_close or self._reconnecting:
            return
        self.notify_connection_lost(compact_error(reason))

    @Slot(str)
    def _connection_action(self, action: str):
        if action == "reconnect":
            self.reconnect_requested.emit()
        elif action == "close":
            self.close_requested.emit()

    def send_session_command(self, command, focus=True):
        """
        Envía una orden sólo a ESTA sesión.

        Se usa para acciones del explorador SFTP (cd/vim) y por diseño no
        emite user_input, por lo que nunca dispara MultiExec.
        """
        if (
            not self.channel
            or self.channel.closed
            or self._disconnect_notified
        ):
            self.status_message.emit(
                (
                    "La terminal local no está disponible."
                    if self.is_local_shell
                    else "La terminal SSH no está disponible."
                )
            )
            return False

        command = str(command).rstrip("\r\n")

        if not command:
            return False

        ok = self.bridge.send_raw(
            command + "\r",
            announce=False
        )

        if ok and focus:
            self.focus_terminal()

        return ok

    def notify_connection_lost(self, reason):
        if self._intentional_close or self._disconnect_notified:
            return

        self._disconnect_notified = True
        self._reader_error = compact_error(reason)
        self.bridge.clear_channel()
        self.bridge.set_disconnected_mode(True)

        if self.is_local_shell:
            self.status_message.emit(
                f"Terminal local finalizada: {self._reader_error}"
            )
            self.bridge.write_output(
                "\r\n\x1b[1;33m"
                "╔══════════════════════════════════════════════════════════╗\r\n"
                "║                 TERMINAL LOCAL FINALIZADA               ║\r\n"
                "╚══════════════════════════════════════════════════════════╝"
                "\x1b[0m\r\n"
                f"\x1b[38;5;220m{self._reader_error}\x1b[0m\r\n\r\n"
                "  \x1b[1;32m[R]\x1b[0m Reiniciar terminal local\r\n"
                "  \x1b[1;33m[Q]\x1b[0m Cerrar pestaña\r\n\r\n"
                "Presiona R o Q dentro de esta terminal.\r\n"
            )
        else:
            self.status_message.emit(
                f"SSH desconectado: {self._reader_error}"
            )
            self.bridge.write_output(
                "\r\n\x1b[1;31m"
                "╔══════════════════════════════════════════════════════════╗\r\n"
                "║              CONEXIÓN SSH INTERRUMPIDA                  ║\r\n"
                "╚══════════════════════════════════════════════════════════╝"
                "\x1b[0m\r\n"
                f"\x1b[38;5;203m{self._reader_error}\x1b[0m\r\n\r\n"
                "  \x1b[1;32m[R]\x1b[0m Reintentar conexión\r\n"
                "  \x1b[1;33m[Q]\x1b[0m Cerrar esta pestaña SSH\r\n\r\n"
                "Presiona R o Q dentro de esta terminal.\r\n"
            )

        self.connection_lost.emit(self._reader_error)

    def begin_reconnect(self):
        if self._reconnecting:
            return
        self._reconnecting = True
        self.bridge.set_disconnected_mode(True)
        self.bridge.write_output(
            (
                "\r\n\x1b[38;5;220m[LOCAL] Reiniciando terminal...\x1b[0m\r\n"
                if self.is_local_shell
                else "\r\n\x1b[38;5;220m[SSH] Reintentando conexión...\x1b[0m\r\n"
            )
        )

    def reconnect_success(self):
        self._stop_shell(intentional=True)
        self._intentional_close = False
        self._shell_started = False
        self._disconnect_notified = False
        self._reader_error = ""
        self._reconnecting = False
        self.bridge.set_disconnected_mode(False)
        self.bridge.write_output(
            (
                "\r\n\x1b[1;32m[LOCAL] Abriendo nuevo ConPTY...\x1b[0m\r\n"
                if self.is_local_shell
                else "\r\n\x1b[1;32m[SSH] Conexión restablecida. Abriendo nuevo PTY...\x1b[0m\r\n"
            )
        )
        self.start()

    def reconnect_failed(self, reason):
        self._reconnecting = False
        self._disconnect_notified = True
        self._reader_error = compact_error(reason)
        self.bridge.clear_channel()
        self.bridge.set_disconnected_mode(True)
        self.bridge.write_output(
            "\r\n\x1b[1;31m[SSH] No fue posible reconectar.\x1b[0m\r\n"
            f"\x1b[38;5;203m{self._reader_error}\x1b[0m\r\n"
            "\x1b[1;32m[R]\x1b[0m Reintentar   "
            "\x1b[1;33m[Q]\x1b[0m Cerrar pestaña\r\n"
        )

    def focus_terminal(self):
        self.view.setFocus()
        self.view.page().runJavaScript(
            "if (window.term) { window.term.focus(); }"
        )

    @Slot(str)
    def _handle_history_shortcut(self, action: str):
        """Navegación local; no escribe nada al canal SSH."""
        safe_action = str(action or "").lower()

        if safe_action not in {
            "pageup", "pagedown", "top", "bottom"
        }:
            return

        self.view.page().runJavaScript(
            "window.mobhectorHistoryNavigate && "
            "window.mobhectorHistoryNavigate("
            + json.dumps(safe_action)
            + ");"
        )

    def fit_terminal(self):
        if not self._page_loaded:
            return
        self.view.page().runJavaScript(
            "if (window.fitTerminal) { window.fitTerminal(); }"
        )

    def schedule_fit_terminal(self, delay_ms=70):
        self._fit_timer.stop()
        self._fit_timer.start(
            max(0, min(1000, int(delay_ms)))
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_fit_terminal(70)

    def showEvent(self, event):
        super().showEvent(event)
        self._reactivate_web_view("showEvent", focus=False)

    def _reactivate_web_view(self, context="reparent", focus=False):
        """
        QWidget cambia a invisible durante un reparent. Para xterm hay que
        volver a mostrar QWidget + QWebEngineView + QWebEnginePage y después
        recalcular el tamaño del PTY.
        """
        try:
            self.setVisible(True)
            self.view.setVisible(True)
            self.view.show()

            page = self.view.page()
            try:
                page.setVisible(True)
            except Exception:
                pass
            try:
                page.setLifecycleState(
                    QWebEnginePage.LifecycleState.Active
                )
            except Exception:
                pass

            self.updateGeometry()
            self.update()
            self.view.update()

            QTimer.singleShot(0, self.redraw_terminal)
            QTimer.singleShot(220, self.redraw_terminal)
            QTimer.singleShot(650, self.redraw_terminal)

            if focus:
                QTimer.singleShot(300, self.focus_terminal)

            QTimer.singleShot(
                320,
                lambda c=context: self._log_render_state(c)
            )
        except Exception:
            LOGGER.exception(
                "No se pudo reactivar QWebEngine después de %s",
                context
            )

    def redraw_terminal(self):
        if self._page_loaded:
            self.view.page().runJavaScript(
                "if (window.fitTerminal) window.fitTerminal();"
                "if (window.term) { window.term.clearTextureAtlas(); window.term.refresh(0, window.term.rows - 1); }"
            )
            self.view.update()

    def reactivate_after_reparent(self, context="reparent", focus=False):
        self.setVisible(True)
        self.show()
        self._reactivate_web_view(context, focus=focus)

    def _log_render_state(self, context):
        try:
            page = self.view.page()
            LOGGER.info(
                "TERMINAL_RENDER context=%s widgetVisible=%s "
                "viewVisible=%s pageVisible=%s size=%sx%s pid=%s",
                context,
                self.isVisible(),
                self.view.isVisible(),
                page.isVisible(),
                self.view.width(),
                self.view.height(),
                page.renderProcessPid(),
            )
        except Exception:
            LOGGER.exception(
                "No se pudo registrar estado QWebEngine (%s)",
                context
            )

    def wheelEvent(self, event):
        super().wheelEvent(event)

    def _zoom_from_wheel(self, direction: int):
        if direction > 0:
            self.zoom_in_custom()
        else:
            self.zoom_out_custom()

    def set_visual_mode(self, mode):
        mode = str(mode or "dark").lower()
        if mode not in (
            "dark", "glass", "light", "coffee",
            "midnight", "forest", "purple", "sepia", "moba", "moba_plain"
        ):
            mode = "dark"
        self.visual_mode = mode
        backgrounds = {
            "moba": QColor("#000000"),
            "moba_plain": QColor("#000000"),
            "dark": QColor("#050607"),
            "light": QColor("#f7f9fc"),
            "coffee": QColor("#efe2cf"),
            "midnight": QColor("#07111f"),
            "forest": QColor("#07130d"),
            "purple": QColor("#130b1b"),
            "sepia": QColor("#f0dfc4"),
        }
        try:
            if mode == "glass":
                self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            else:
                self.view.page().setBackgroundColor(
                    backgrounds.get(mode, QColor("#050607"))
                )
        except Exception:
            LOGGER.exception("No se pudo cambiar fondo de QWebEngine")
        self._apply_visual_mode_js()

    def _apply_visual_mode_js(self):
        if not getattr(self, "_page_loaded", False):
            return
        mode = json.dumps(self.visual_mode)
        self.view.page().runJavaScript(
            "if (window.setTerminalTheme) { "
            f"window.setTerminalTheme({mode});"
            " }"
        )

    def set_terminal_preferences(self, preferences):
        prefs = dict(preferences or {})
        current = dict(self.terminal_preferences)

        self.terminal_preferences = {
            "font_family": str(
                prefs.get("font_family", current.get("font_family", "Cascadia Mono"))
            ),
            "font_size": max(
                9, min(26, int(prefs.get("font_size", current.get("font_size", 14))))
            ),
            "cursor_style": (
                str(prefs.get("cursor_style", current.get("cursor_style", "block")))
                if str(prefs.get("cursor_style", current.get("cursor_style", "block")))
                in ("block", "bar", "underline")
                else "block"
            ),
            "cursor_blink": bool(
                prefs.get("cursor_blink", current.get("cursor_blink", True))
            ),
            "scrollback": max(
                5000,
                min(
                    1000000,
                    int(
                        prefs.get(
                            "scrollback",
                            current.get("scrollback", 500000)
                        )
                    )
                )
            ),
            "history_sticky": bool(
                prefs.get(
                    "history_sticky",
                    current.get("history_sticky", True)
                )
            ),
            "protect_scrollback": bool(
                prefs.get(
                    "protect_scrollback",
                    current.get("protect_scrollback", True)
                )
            ),
            "selection_autoscroll": bool(
                prefs.get(
                    "selection_autoscroll",
                    current.get("selection_autoscroll", True)
                )
            ),
            "line_height": max(
                90,
                min(
                    160,
                    int(prefs.get("line_height", current.get("line_height", 108)))
                )
            ),
            "bold_bright": bool(
                prefs.get("bold_bright", current.get("bold_bright", True))
            ),
            "click_to_cursor": bool(
                prefs.get("click_to_cursor", current.get("click_to_cursor", True))
            ),
            "tui_native_mouse": bool(
                prefs.get(
                    "tui_native_mouse",
                    current.get("tui_native_mouse", True)
                )
            ),
            "tui_arrow_fallback": bool(
                prefs.get(
                    "tui_arrow_fallback",
                    current.get("tui_arrow_fallback", True)
                )
            ),
            "middle_click_paste": bool(
                prefs.get("middle_click_paste", current.get("middle_click_paste", False))
            ),
            "bell_style": (
                str(prefs.get("bell_style", current.get("bell_style", "none")))
                if str(prefs.get("bell_style", current.get("bell_style", "none")))
                in ("none", "visual", "sound") else "none"
            ),
            "word_mode": (
                str(prefs.get("word_mode", current.get("word_mode", "unix")))
                if str(prefs.get("word_mode", current.get("word_mode", "unix")))
                in ("unix", "strict", "spaces") else "unix"
            ),
            "show_scrollbar": bool(
                prefs.get("show_scrollbar", current.get("show_scrollbar", True))
            ),
        }
        self._apply_terminal_preferences_js()

    def _apply_terminal_preferences_js(self):
        if not getattr(self, "_page_loaded", False):
            return

        payload = json.dumps(self.terminal_preferences)
        self.view.page().runJavaScript(
            "if (window.setTerminalPreferences) { "
            f"window.setTerminalPreferences({payload});"
            " }"
        )

    def set_clipboard_preferences(self, preferences):
        prefs = dict(preferences or {})
        self.clipboard_preferences = {
            "auto_copy_selection": bool(
                prefs.get(
                    "auto_copy_selection",
                    self.clipboard_preferences.get(
                        "auto_copy_selection", True
                    )
                )
            ),
            "ctrl_v_paste": bool(
                prefs.get(
                    "ctrl_v_paste",
                    self.clipboard_preferences.get(
                        "ctrl_v_paste", True
                    )
                )
            ),
            "right_click_paste": bool(
                prefs.get(
                    "right_click_paste",
                    self.clipboard_preferences.get(
                        "right_click_paste", True
                    )
                )
            ),
        }
        self._apply_clipboard_preferences_js()

    def _apply_clipboard_preferences_js(self):
        if not getattr(self, "_page_loaded", False):
            return

        payload = json.dumps(self.clipboard_preferences)
        self.view.page().runJavaScript(
            "if (window.setClipboardPreferences) { "
            f"window.setClipboardPreferences({payload});"
            " }"
        )

    def _apply_zoom_js(self):
        self.view.page().runJavaScript(
            f"if (window.setTerminalZoom) "
            f"{{ window.setTerminalZoom({int(self.zoom_percent)}); }}"
        )
        self.zoom_changed.emit(self.zoom_percent)

    def zoom_in_custom(self):
        self.zoom_percent = min(220, self.zoom_percent + 10)
        self._apply_zoom_js()

    def zoom_out_custom(self):
        self.zoom_percent = max(60, self.zoom_percent - 10)
        self._apply_zoom_js()

    def zoom_reset_custom(self):
        self.zoom_percent = 100
        self._apply_zoom_js()

    def clear(self):
        # Limpieza visual sin borrar scrollback.
        self.view.page().runJavaScript(
            "if (window.mobhectorClearVisible) "
            "{ window.mobhectorClearVisible(); }"
        )

    def copy_selection(self):
        self.view.page().runJavaScript(
            "if (window.copyTerminalSelection) "
            "{ window.copyTerminalSelection(); }"
        )

    def paste_clipboard(self):
        self.view.page().runJavaScript(
            "if (window.pasteTerminalClipboard) "
            "{ window.pasteTerminalClipboard(); }"
        )

    def send_multi_exec_input(self, data: str):
        if self._disconnect_notified or self._reconnecting:
            return False
        return self.bridge.send_raw(data, announce=False)

    def send_multi_exec_paste(self, data: str):
        """
        Envía un bloque MultiExec respetando bracketedPasteMode
        de ESTA terminal destino y sin reemitir MultiExec.
        """
        if (
            self._disconnect_notified
            or self._reconnecting
            or not self.channel
            or self.channel.closed
        ):
            return False

        payload = str(data)

        def deliver(bracketed):
            if (
                self._disconnect_notified
                or self._reconnecting
                or not self.channel
                or self.channel.closed
            ):
                return

            outgoing = payload
            if bool(bracketed):
                outgoing = (
                    "\x1b[200~"
                    + payload
                    + "\x1b[201~"
                )

            self.bridge.send_raw(
                outgoing,
                announce=False
            )

        try:
            self.view.page().runJavaScript(
                "Boolean(window.term && term.modes && "
                "term.modes.bracketedPasteMode)",
                deliver,
            )
            return True
        except Exception:
            LOGGER.exception(
                "No se pudo consultar bracketed paste en destino MultiExec"
            )
            return self.bridge.send_raw(
                payload,
                announce=False
            )

    def _stop_shell(self, intentional=True):
        if intentional:
            self._intentional_close = True

        reader = self.reader
        channel = self.channel

        self.reader = None
        self.channel = None
        self.bridge.clear_channel()

        if reader:
            try:
                reader.stop()
            except Exception:
                pass

        try:
            if channel:
                channel.close()
        except Exception:
            pass

        if reader:
            try:
                stopped = reader.wait(700)
            except Exception:
                stopped = False

            if not stopped and reader.isRunning():
                _RETIRED_TERMINAL_READERS.add(reader)
                try:
                    reader.finished.connect(
                        lambda r=reader:
                            _release_retired_terminal_reader(r)
                    )
                except Exception:
                    pass

    def close_terminal(self):
        self.stop_transcript()
        self._stop_shell(intentional=True)
        self.bridge.set_disconnected_mode(False)


# ============================================================
# Transfer dock
# ============================================================

class TransferDock(QDockWidget):
    """
    Cola visual de transferencias.

    Cada fila tiene una QProgressBar real. El dock es opcional y sólo
    se muestra por acción explícita del usuario.
    """
    def __init__(self, parent=None):
        super().__init__("Transferencias", parent)
        self.setObjectName("TransferDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(7, 7, 7, 7)
        lay.setSpacing(6)

        header = QHBoxLayout()
        self.summary = QLabel("Sin transferencias activas")
        self.summary.setObjectName("transferSummary")
        header.addWidget(self.summary)
        header.addStretch()

        cancel = QPushButton("Cancelar seleccionada")
        cancel.clicked.connect(self.cancel_selected)
        header.addWidget(cancel)
        clear = QPushButton("Limpiar finalizadas")
        clear.clicked.connect(self.clear_finished)
        header.addWidget(clear)
        lay.addLayout(header)

        self.table = QTreeWidget()
        self.table.setObjectName("transferTable")
        self.table.setHeaderLabels(
            ["Tipo", "Elemento", "Destino", "Progreso", "Estado"]
        )
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.header().resizeSection(3, 190)
        self.table.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        self.setWidget(body)

        self.items = {}
        self.bars = {}
        self.states = {}
        self.max_history_rows = 300
        self.cancel_events = {}

    def cancel_selected(self):
        selected = self.table.currentItem()
        for tid, item in self.items.items():
            if item is selected and tid in self.cancel_events:
                self.cancel_events[tid].set()
                item.setText(4, "Cancelando…")
                break

    def cancel_all(self):
        for event in self.cancel_events.values():
            event.set()

    def _prune_history(self):
        """Limita crecimiento de widgets si la app permanece abierta días."""
        while self.table.topLevelItemCount() > self.max_history_rows:
            removable_index = None
            for i in range(self.table.topLevelItemCount()):
                item = self.table.topLevelItem(i)
                if item.data(0, Qt.ItemDataRole.UserRole) == "finished":
                    removable_index = i
                    break
            if removable_index is None:
                return

            item = self.table.topLevelItem(removable_index)
            tid_to_remove = next(
                (tid for tid, known in self.items.items() if known is item),
                None
            )
            self.table.takeTopLevelItem(removable_index)
            if tid_to_remove:
                self.items.pop(tid_to_remove, None)
                self.bars.pop(tid_to_remove, None)
                self.states.pop(tid_to_remove, None)

    def _refresh_summary(self):
        active = sum(1 for state in self.states.values() if state == "active")
        completed = sum(1 for state in self.states.values() if state == "done")
        failed = sum(1 for state in self.states.values() if state == "error")

        if active:
            self.summary.setText(
                f"● {active} transferencia(s) activa(s)"
                + (f"  •  {completed} completada(s)" if completed else "")
            )
        elif failed:
            self.summary.setText(
                f"Sin transferencias activas  •  {failed} con error"
            )
        elif completed:
            self.summary.setText(
                f"Sin transferencias activas  •  {completed} completada(s)"
            )
        else:
            self.summary.setText("Sin transferencias activas")

    def start_transfer(self, tid, op, src, dst):
        item = QTreeWidgetItem([op, src, dst, "", "Preparando..."])
        self.table.addTopLevelItem(item)

        bar = QProgressBar()
        bar.setObjectName("transferProgress")
        bar.setRange(0, 0)  # indeterminado mientras calcula/prepara
        bar.setTextVisible(True)
        bar.setFormat("Preparando…")
        bar.setMinimumHeight(22)

        self.table.setItemWidget(item, 3, bar)

        self.items[tid] = item
        self.bars[tid] = bar
        self.states[tid] = "active"
        self._prune_history()
        self._refresh_summary()

        # La tarjeta inline del SFTP es el feedback principal.
        # La cola inferior NO se abre automáticamente.
        self.table.scrollToItem(item)

    def update_transfer(
        self,
        tid,
        percent=0,
        detail="",
        stage="transferring",
        meta=""
    ):
        item = self.items.get(tid)
        bar = self.bars.get(tid)
        if not item or not bar:
            return

        if stage == "preparing":
            bar.setRange(0, 0)
            bar.setFormat("Preparando…")
            status = detail or "Preparando..."

        elif stage == "complete":
            # El motor sólo emite complete DESPUÉS de cerrar/verificar el archivo.
            # Por eso la cola puede finalizar aquí sin depender de finished().
            bar.setRange(0, 100)
            bar.setValue(100)
            bar.setFormat("100%")
            status = "✓ Completado"
            if detail:
                status += f"  •  {detail}"
            if meta:
                status += f"  •  {meta}"
            self.states[tid] = "done"
            item.setData(0, Qt.ItemDataRole.UserRole, "finished")
            self._refresh_summary()

        else:
            value = max(0, min(99, int(percent)))
            if bar.minimum() == 0 and bar.maximum() == 0:
                bar.setRange(0, 100)
            bar.setValue(value)
            bar.setFormat(f"{value}%")
            status = detail or "Transfiriendo"
            if meta:
                status += f"  •  {meta}"

        item.setText(4, status)
        self.table.scrollToItem(item)

    def finish_transfer(self, tid, ok, detail=""):
        item = self.items.get(tid)
        bar = self.bars.get(tid)
        if not item or not bar:
            return

        if bar.minimum() == 0 and bar.maximum() == 0:
            bar.setRange(0, 100)

        if ok:
            bar.setValue(100)
            bar.setFormat("100%")
            item.setText(4, detail or "✓ Completado")
            self.states[tid] = "done"
        elif detail.startswith("Cancelada"):
            bar.setFormat("Cancelada")
            item.setText(4, detail)
            self.states[tid] = "cancelled"
        else:
            bar.setFormat("Error")
            item.setText(4, detail or "✕ Error")
            self.states[tid] = "error"

        item.setData(0, Qt.ItemDataRole.UserRole, "finished")
        self._prune_history()
        self._refresh_summary()

    def clear_finished(self):
        for i in reversed(range(self.table.topLevelItemCount())):
            item = self.table.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == "finished":
                tid_to_remove = None
                for tid, known_item in self.items.items():
                    if known_item is item:
                        tid_to_remove = tid
                        break
                self.table.takeTopLevelItem(i)
                if tid_to_remove:
                    self.items.pop(tid_to_remove, None)
                    self.bars.pop(tid_to_remove, None)
                    self.states.pop(tid_to_remove, None)
        self._refresh_summary()


# ============================================================
# Local browser
# ============================================================

class LocalBrowser(QWidget):
    upload_requested = Signal(list)
    path_changed = Signal(str)

    def __init__(self, initial_path, parent=None):
        super().__init__(parent)
        self.current_path = initial_path if os.path.isdir(initial_path) else safe_local_start()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        nav = QHBoxLayout()
        up = QToolButton(); up.setText("↑"); up.clicked.connect(self.go_up)
        home = QToolButton(); home.setText("⌂"); home.clicked.connect(self.go_home)
        nav.addWidget(up); nav.addWidget(home)

        self.path_edit = QLineEdit(self.current_path)
        self.path_edit.returnPressed.connect(self.go_path)
        nav.addWidget(self.path_edit, 1)

        refresh = QToolButton(); refresh.setText("↻"); refresh.clicked.connect(self.refresh)
        nav.addWidget(refresh)
        lay.addLayout(nav)

        self.model = QFileSystemModel(self)
        self.model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot |
            QDir.Filter.Hidden | QDir.Filter.System
        )
        self.model.setRootPath(self.current_path)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.current_path))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 280)
        self.tree.header().resizeSection(1, 120)
        self.tree.header().resizeSection(2, 170)
        self.tree.header().resizeSection(3, 160)
        self.tree.doubleClicked.connect(self.open_index)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        lay.addWidget(self.tree, 1)

        send = QPushButton("Subir selección →")
        send.clicked.connect(self.emit_upload)
        lay.addWidget(send)

    def selected_paths(self):
        result = []
        seen = set()
        for index in self.tree.selectionModel().selectedRows(0):
            p = self.model.filePath(index)
            if p not in seen:
                result.append(p)
                seen.add(p)
        return result

    def set_path(self, path):
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Windows", "La ruta no es válida.")
            return
        self.current_path = path
        self.model.setRootPath(path)
        self.tree.setRootIndex(self.model.index(path))
        self.path_edit.setText(path)
        self.path_changed.emit(path)

    def go_path(self):
        self.set_path(self.path_edit.text().strip().strip('"'))

    def go_up(self):
        p = str(Path(self.current_path).parent)
        if p != self.current_path:
            self.set_path(p)

    def go_home(self):
        self.set_path(safe_local_start())

    def refresh(self):
        current = self.current_path
        self.model.setRootPath("")
        self.model.setRootPath(current)
        self.tree.setRootIndex(self.model.index(current))

    def open_index(self, idx):
        p = self.model.filePath(idx)
        if os.path.isdir(p):
            self.set_path(p)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def emit_upload(self):
        paths = self.selected_paths()
        if paths:
            self.upload_requested.emit(paths)
        else:
            QMessageBox.information(self, "Subir", "Selecciona archivos o carpetas.")

    def context_menu(self, pos):
        menu = QMenu(self)
        open_a = menu.addAction("Abrir / Entrar")
        upload_a = menu.addAction("Subir al servidor")
        menu.addSeparator()
        copy_a = menu.addAction("Copiar ruta")
        explorer_a = menu.addAction("Abrir en Explorer")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        paths = self.selected_paths()
        if chosen == open_a and paths:
            p = paths[0]
            if os.path.isdir(p):
                self.set_path(p)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
        elif chosen == upload_a:
            self.emit_upload()
        elif chosen == copy_a and paths:
            QApplication.clipboard().setText(paths[0])
        elif chosen == explorer_a:
            p = paths[0] if paths else self.current_path
            if os.path.isfile(p):
                subprocess.Popen(["explorer.exe", "/select,", p])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))


# ============================================================
# Search
# ============================================================

class SearchDialog(QDialog):
    download_requested = Signal(list)

    def __init__(self, connection, base_path, pool, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.base_path = base_path
        self.pool = pool
        self.resize(1050, 650)
        self.setWindowTitle("Buscar en servidor")

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.term = QLineEdit()
        self.term.setPlaceholderText("Nombre o parte del nombre...")
        self.term.returnPressed.connect(self.search)
        top.addWidget(self.term, 1)
        self.max_results = QSpinBox()
        self.max_results.setRange(20, 2000)
        self.max_results.setValue(500)
        top.addWidget(QLabel("Máx:"))
        top.addWidget(self.max_results)
        btn = QPushButton("Buscar")
        btn.clicked.connect(self.search)
        top.addWidget(btn)
        lay.addLayout(top)

        self.info = QLabel(f"Base: {base_path}")
        self.info.setObjectName("muted")
        lay.addWidget(self.info)

        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Tipo", "Ruta", "Tamaño", "Modificado"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        download = QPushButton("Descargar selección")
        download.clicked.connect(self.emit_download)
        bottom.addWidget(download)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)

    def search(self):
        term = self.term.text().strip()
        if not term:
            return

        limit = self.max_results.value()
        self.info.setText(f"Buscando '{term}'...")

        def work(progress):
            """
            GNU find es muy rápido en Linux. En Solaris/AIX u otros Unix
            donde -printf/-- no existen, se usa SFTP recursivo portable.
            """
            pattern = "*" + term + "*"
            fast_cmd = (
                "find --version >/dev/null 2>&1 && "
                f"find -- {shlex.quote(self.base_path)} "
                f"-iname {shlex.quote(pattern)} "
                r"-printf '%y\0%p\0%s\0%TY-%Tm-%Td %TH:%TM\0' "
                "2>/dev/null | head -c 8000000"
            )

            try:
                rc, out, _err = self.connection.exec(
                    fast_cmd,
                    timeout=90
                )
            except Exception:
                rc, out = 1, b""

            if rc in (0, 141) and out:
                fields = out.split(b"\0")
                if fields and fields[-1] == b"":
                    fields.pop()

                rows = []
                for i in range(0, len(fields), 4):
                    if (
                        len(rows) >= limit
                        or i + 3 >= len(fields)
                    ):
                        break

                    typ = fields[i].decode(
                        "utf-8",
                        errors="replace"
                    )
                    path = fields[i + 1].decode(
                        "utf-8",
                        errors="replace"
                    )
                    try:
                        size = int(fields[i + 2].decode())
                    except Exception:
                        size = 0
                    modified = fields[i + 3].decode(
                        "utf-8",
                        errors="replace"
                    )
                    rows.append({
                        "type": typ,
                        "path": path,
                        "size": size,
                        "modified": modified,
                    })

                return {
                    "rows": rows,
                    "backend": "GNU find",
                    "truncated": len(rows) >= limit,
                }

            # Fallback portable: no depende de GNU userland ni Python remoto.
            needle = term.casefold()
            rows = []
            stack = [self.base_path]
            scanned_dirs = 0
            max_dirs = 8000

            sftp = self.connection.open_sftp_session()
            try:
                while stack and len(rows) < limit:
                    current = stack.pop()
                    scanned_dirs += 1
                    if scanned_dirs > max_dirs:
                        break

                    try:
                        attrs = sftp.listdir_attr(current)
                    except (IOError, OSError):
                        continue

                    for attr in attrs:
                        name = attr.filename
                        if name in (".", ".."):
                            continue

                        path = remote_join(current, name)
                        mode = int(attr.st_mode or 0)

                        if stat.S_ISDIR(mode):
                            typ = "d"
                            stack.append(path)
                        elif stat.S_ISLNK(mode):
                            typ = "l"
                        else:
                            typ = "f"

                        if needle not in name.casefold():
                            continue

                        rows.append({
                            "type": typ,
                            "path": path,
                            "size": int(attr.st_size or 0),
                            "modified": fmt_mtime(
                                float(attr.st_mtime or 0)
                            ),
                        })

                        if len(rows) >= limit:
                            break
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass

            return {
                "rows": rows,
                "backend": "SFTP portable",
                "truncated": bool(
                    len(rows) >= limit
                    or scanned_dirs > max_dirs
                ),
            }

        worker = Worker(work)
        worker.signals.finished.connect(self.show_results)
        worker.signals.error.connect(
            lambda e: QMessageBox.critical(
                self,
                "Buscar",
                compact_error(e)
            )
        )
        self.pool.start(worker)

    def show_results(self, result):
        if isinstance(result, dict):
            rows = list(result.get("rows", []))
            backend = result.get("backend", "")
            truncated = bool(result.get("truncated"))
        else:
            rows = list(result or [])
            backend = ""
            truncated = False

        self.table.clear()
        for row in rows:
            label = "DIR" if row["type"] == "d" else ("LINK" if row["type"] == "l" else "FILE")
            item = QTreeWidgetItem([
                label,
                row["path"],
                "" if row["type"] == "d" else human_size(row["size"]),
                row["modified"]
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.table.addTopLevelItem(item)
        suffix = f" • {backend}" if backend else ""
        if truncated:
            suffix += " • resultados limitados"
        self.info.setText(
            f"{len(rows)} resultado(s){suffix}"
        )

    def emit_download(self):
        rows = []
        for item in self.table.selectedItems():
            row = item.data(0, Qt.ItemDataRole.UserRole)
            if row:
                rows.append(row)
        if rows:
            self.download_requested.emit(rows)


# ============================================================
# Remote editor
# ============================================================

class RemoteEditor(QWidget):
    def __init__(self, connection, remote_path, pool, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.remote_path = remote_path
        self.pool = pool
        self.changed = False
        self._original_digest = None
        self._newline = "\n"
        self._utf8_bom = False
        self._saving = False

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        path_label = QLabel(remote_path)
        path_label.setObjectName("muted")
        top.addWidget(path_label, 1)
        save = QPushButton("Guardar")
        save.clicked.connect(self.save_remote)
        top.addWidget(save)
        lay.addLayout(top)

        self.editor = QPlainTextEdit()
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed.setFamily("Cascadia Mono")
        fixed.setPointSize(11)
        self.editor.setFont(fixed)
        self.editor.textChanged.connect(lambda: setattr(self, "changed", True))
        lay.addWidget(self.editor, 1)
        self.load_remote()

    def load_remote(self):
        def work(progress):
            self.connection.ensure()
            sftp = self.connection.open_sftp_session()
            try:
                info = sftp.lstat(self.remote_path)

                if not stat.S_ISREG(info.st_mode):
                    raise IsADirectoryError(
                        f"{self.remote_path} es un directorio. "
                        "Usa 'Abrir terminal aquí' o entra en la carpeta."
                    )

                with sftp.open(self.remote_path, "rb") as fh:
                    raw = fh.read(3 * 1024 * 1024 + 1)
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass
            if len(raw) > 3 * 1024 * 1024:
                raise RuntimeError("Archivo demasiado grande para el editor integrado (>3 MB).")
            return decode_document(raw)

        w = Worker(work)
        w.signals.finished.connect(self._loaded)
        w.signals.error.connect(lambda e: QMessageBox.critical(self, "Editor", compact_error(e)))
        self.pool.start(w)

    def _loaded(self, result):
        text, self._original_digest, self._newline, self._utf8_bom = result
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.changed = False

    def save_remote(self):
        if self._original_digest is None or self._saving:
            return
        self._saving = True
        data = encode_document(self.editor.toPlainText(), self._newline, self._utf8_bom)
        original_digest = self._original_digest
        saved_text = self.editor.toPlainText()

        def work(progress):
            self.connection.ensure()
            sftp = self.connection.open_sftp_session()
            temp_path = (
                self.remote_path
                + f".mobhector-edit-{uuid.uuid4().hex}"
            )
            backup_path = None
            try:
                original = sftp.lstat(self.remote_path)
                if not stat.S_ISREG(original.st_mode):
                    raise ValueError("El destino ya no es un archivo regular")
                original_mode = stat.S_IMODE(original.st_mode)
                with sftp.open(self.remote_path, "rb") as existing:
                    current = existing.read(3 * 1024 * 1024 + 1)
                if hashlib.sha256(current).hexdigest() != original_digest:
                    raise RuntimeError("El archivo cambió en el servidor. Guarda una copia local y vuelve a abrirlo antes de sobrescribirlo.")

                with sftp.open(temp_path, "wb") as fh:
                    fh.write(data)
                    try:
                        fh.flush()
                    except Exception:
                        pass

                written = int(sftp.stat(temp_path).st_size or 0)
                if written != len(data):
                    raise RuntimeError(
                        "El archivo temporal remoto no tiene el tamaño esperado."
                    )

                try:
                    sftp.chmod(temp_path, original_mode)
                except Exception:
                    pass

                posix_rename = getattr(sftp, "posix_rename", None)
                if callable(posix_rename):
                    try:
                        posix_rename(temp_path, self.remote_path)
                        temp_path = None
                        return True
                    except Exception:
                        pass

                backup_path = (
                    self.remote_path
                    + f".mobhector-backup-{uuid.uuid4().hex}"
                )
                sftp.rename(self.remote_path, backup_path)
                try:
                    sftp.rename(temp_path, self.remote_path)
                    temp_path = None
                except Exception:
                    try:
                        sftp.rename(backup_path, self.remote_path)
                        backup_path = None
                    except Exception:
                        pass
                    raise

                try:
                    sftp.remove(backup_path)
                    backup_path = None
                except Exception:
                    pass
                return True

            finally:
                if temp_path:
                    try:
                        sftp.remove(temp_path)
                    except Exception:
                        pass
                try:
                    sftp.close()
                except Exception:
                    pass

        w = Worker(work)
        def saved(result):
            self._saving = False
            self._original_digest = hashlib.sha256(data).hexdigest()
            self._saved(result)
            self.changed = self.editor.toPlainText() != saved_text
        w.signals.finished.connect(saved)
        w.signals.error.connect(lambda e: setattr(self, "_saving", False))
        w.signals.error.connect(
            lambda e: QMessageBox.critical(
                self,
                "Guardar",
                compact_error(e)
            )
        )
        self.pool.start(w)

    def _saved(self, _):
        self.changed = False
        QMessageBox.information(
            self,
            "Editor",
            "Archivo guardado en el servidor."
        )


# ============================================================
# Remote browser
# ============================================================

class RemoteTree(QTreeWidget):
    local_drop = Signal(list)
    drag_state_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("remoteTree")
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)

        self.drop_active = False
        self.empty_message = (
            "Esta carpeta está vacía\n"
            "Arrastra archivos aquí para subirlos"
        )
        self.drop_message = "Suelta aquí para subir al servidor"

    def set_empty_message(self, text):
        self.empty_message = text
        self.viewport().update()

    def set_drop_message(self, text):
        self.drop_message = text
        self.viewport().update()

    def _set_drop_active(self, active):
        active = bool(active)
        if self.drop_active == active:
            return
        self.drop_active = active
        self.drag_state_changed.emit(active)
        self.viewport().update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if any(paths):
                self._set_drop_active(True)
                event.acceptProposedAction()
                return
        self._set_drop_active(False)
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_active(False)
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            paths = [p for p in paths if p and os.path.exists(p)]
            if paths:
                self.local_drop.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.viewport().rect()

        if self.drop_active:
            painter.fillRect(rect, QColor(30, 112, 122, 54))
            border = rect.adjusted(9, 9, -9, -9)
            pen = QPen(QColor("#65d9d4"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRoundedRect(border, 9, 9)

            font = painter.font()
            font.setPointSize(max(11, font.pointSize() + 1))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#8ff1ec"))
            painter.drawText(
                border.adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter,
                self.drop_message
            )

        elif self.topLevelItemCount() == 0:
            painter.setPen(QColor("#657080"))
            font = painter.font()
            font.setPointSize(max(10, font.pointSize()))
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(24, 24, -24, -24),
                Qt.AlignmentFlag.AlignCenter,
                self.empty_message
            )

        painter.end()


class RemoteBrowser(QWidget):
    open_editor = Signal(str)
    open_terminal_here = Signal(str)
    open_vim = Signal(str)
    status_message = Signal(str)

    def __init__(self, connection, session, pool, transfers, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.session = session
        self.pool = pool
        self.transfers = transfers
        self.current_path = (
            session.get("_resolved_remote_home")
            or session.get("remote_home")
            or "/"
        )
        self.local_browser = None
        self._all_rows = []
        self._refresh_generation = 0
        self.current_activity_tid = None
        self._activity_hide_token = 0

        # Mantener referencias fuertes a QRunnable/Worker mientras están
        # ejecutándose. Sin esto, el wrapper Python puede ser recolectado
        # antes de que lleguen progress/finished/error a la UI.
        self._transfer_workers = {}
        # SFTP remoto: reutiliza el proveedor de iconos del shell local.
        # En Windows, QFileIconProvider consulta las asociaciones del sistema,
        # por lo que .xlsx/.docx/.pdf/.html muestran los mismos iconos que el
        # explorador local sin descargar el archivo remoto. Se cachea por
        # extensión para que carpetas grandes sigan refrescando rápido.
        self._shell_icon_provider = QFileIconProvider()
        self._remote_icon_cache = {}
        self._folder_icon = self._shell_icon_provider.icon(
            QFileIconProvider.IconType.Folder
        )
        self._file_icon = self._shell_icon_provider.icon(
            QFileIconProvider.IconType.File
        )
        self._link_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileLinkIcon
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        nav = QHBoxLayout()
        up = QToolButton(); up.setText("↑"); up.setToolTip("Subir"); up.clicked.connect(self.go_up)
        home = QToolButton(); home.setText("⌂"); home.setToolTip("Home"); home.clicked.connect(self.go_home)
        inbox = QToolButton(); inbox.setText("⇩"); inbox.setToolTip("archivos_enviados"); inbox.clicked.connect(self.go_inbox)
        nav.addWidget(up); nav.addWidget(home); nav.addWidget(inbox)

        self.path_edit = QLineEdit(self.current_path)
        self.path_edit.returnPressed.connect(self.go_path)
        nav.addWidget(self.path_edit, 1)

        refresh = QToolButton(); refresh.setText("↻"); refresh.clicked.connect(self.refresh)
        search = QToolButton(); search.setText("⌕"); search.clicked.connect(self.search)
        nav.addWidget(refresh); nav.addWidget(search)
        lay.addLayout(nav)

        filter_lay = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar carpeta...")
        self.filter_edit.textChanged.connect(self._schedule_filter)
        filter_lay.addWidget(self.filter_edit, 1)
        self.hidden = QCheckBox("Ocultos")
        self.hidden.setChecked(
            bool(session.get("_sftp_show_hidden_default", True))
        )
        self.hidden.toggled.connect(self.apply_filter)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(140)
        self._filter_timer.timeout.connect(self.apply_filter)
        filter_lay.addWidget(self.hidden)
        lay.addLayout(filter_lay)

        self.folder_status = QLabel("Listo")
        self.folder_status.setObjectName("remoteFolderStatus")
        lay.addWidget(self.folder_status)

        # Tarjeta visual de transferencia dentro de la MISMA pestaña SFTP.
        # Debe ser evidente incluso si el dock inferior está cerrado.
        self.activity_frame = QFrame()
        self.activity_frame.setObjectName("transferActivityCard")
        self.activity_frame.setMinimumHeight(136)

        activity_layout = QVBoxLayout(self.activity_frame)
        activity_layout.setContentsMargins(14, 11, 14, 11)
        activity_layout.setSpacing(7)

        activity_top = QHBoxLayout()

        self.activity_icon = QLabel("⇧")
        self.activity_icon.setObjectName("transferActivityIcon")
        self.activity_icon.setFixedWidth(28)
        activity_top.addWidget(self.activity_icon)

        self.activity_title = QLabel("Transferencia")
        self.activity_title.setObjectName("transferActivityTitle")
        activity_top.addWidget(self.activity_title, 1)

        self.activity_percent = QLabel("")
        self.activity_percent.setObjectName("transferActivityPercent")
        activity_top.addWidget(self.activity_percent)

        self.activity_queue_button = QPushButton("Ver cola")
        self.activity_queue_button.setObjectName("transferQueueButton")
        self.activity_queue_button.setToolTip(
            "Mostrar el historial de transferencias"
        )
        self.activity_queue_button.clicked.connect(self.show_transfer_queue)
        activity_top.addWidget(self.activity_queue_button)

        activity_layout.addLayout(activity_top)

        self.activity_file = QLabel("")
        self.activity_file.setObjectName("transferActivityFile")
        self.activity_file.setWordWrap(False)
        activity_layout.addWidget(self.activity_file)

        self.activity_bar = QProgressBar()
        self.activity_bar.setObjectName("inlineTransferProgress")
        self.activity_bar.setRange(0, 100)
        self.activity_bar.setValue(0)
        self.activity_bar.setTextVisible(True)
        self.activity_bar.setFormat("%p%")
        self.activity_bar.setMinimumHeight(20)
        self.activity_bar.setMaximumHeight(20)
        activity_layout.addWidget(self.activity_bar)

        info_row = QHBoxLayout()

        self.activity_detail = QLabel("")
        self.activity_detail.setObjectName("transferActivityDetail")
        self.activity_detail.setWordWrap(True)
        info_row.addWidget(self.activity_detail, 1)

        self.activity_destination = QLabel("")
        self.activity_destination.setObjectName("transferActivityDestination")
        self.activity_destination.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        info_row.addWidget(self.activity_destination)

        activity_layout.addLayout(info_row)

        self.activity_frame.hide()
        lay.addWidget(self.activity_frame)

        self.tree = RemoteTree()
        self.tree.setHeaderLabels(["Nombre", "Tamaño", "Fecha", "Permisos"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        # ResizeToContents recalcula ancho contra todas las filas y se vuelve
        # caro en carpetas grandes. Anchos interactivos son constantes.
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 300)
        self.tree.header().resizeSection(1, 105)
        self.tree.header().resizeSection(2, 145)
        self.tree.header().resizeSection(3, 105)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemSelectionChanged.connect(self.update_selection_status)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.local_drop.connect(self.upload_paths)
        self.tree.drag_state_changed.connect(self._drag_state_changed)
        self.tree.set_drop_message(
            f"Suelta aquí para subir a\n{self.current_path}"
        )
        lay.addWidget(self.tree, 1)

        self.selection_status = QLabel("0 seleccionados")
        self.selection_status.setObjectName("selectionStatus")
        lay.addWidget(self.selection_status)

        # Atajos del explorador remoto.
        self.shortcut_rename = QShortcut(QKeySequence("F2"), self.tree)
        self.shortcut_rename.activated.connect(self.rename_selected_shortcut)
        self.shortcut_delete = QShortcut(QKeySequence("Delete"), self.tree)
        self.shortcut_delete.activated.connect(self.delete_selected_shortcut)



        bottom = QHBoxLayout()
        upload = QPushButton("Subir aquí")
        upload.clicked.connect(self.choose_upload)
        download = QPushButton("Descargar")
        download.clicked.connect(self.download_selected)
        new_folder = QPushButton("Nueva carpeta")
        new_folder.clicked.connect(self.new_folder)
        bottom.addWidget(upload); bottom.addWidget(download)
        bottom.addStretch(); bottom.addWidget(new_folder)
        lay.addLayout(bottom)

    def _icon_for_remote_row(self, row):
        row_type = str(row.get("type") or "f")
        if row_type == "d":
            return self._folder_icon
        if row_type == "l":
            return self._link_icon

        name = str(row.get("name") or "")
        suffix = Path(name).suffix.casefold()
        cache_key = suffix or "<no-extension>"
        cached = self._remote_icon_cache.get(cache_key)
        if cached is not None:
            return cached

        icon = self._file_icon
        if suffix:
            try:
                # QFileInfo no necesita que el archivo remoto exista para que
                # Windows resuelva el icono registrado por extensión.
                probe = QFileInfo("mobhector_remote" + suffix)
                resolved = self._shell_icon_provider.icon(probe)
                if not resolved.isNull():
                    icon = resolved
            except Exception:
                LOGGER.debug(
                    "No se pudo resolver icono shell para %s",
                    suffix,
                    exc_info=True,
                )

        self._remote_icon_cache[cache_key] = icon
        return icon

    def effective_home(self):
        return (
            self.session.get("_resolved_remote_home")
            or self.session.get("remote_home")
            or "/"
        )

    def effective_inbox(self):
        return (
            self.session.get("_resolved_remote_inbox")
            or self.session.get("remote_inbox")
            or remote_join(
                self.effective_home(),
                "archivos_enviados"
            )
        )

    def set_local_browser(self, browser):
        self.local_browser = browser

    def selected_rows(self):
        rows = []
        for item in self.tree.selectedItems():
            row = item.data(0, Qt.ItemDataRole.UserRole)
            if row:
                rows.append(row)
        return rows

    def refresh(self):
        path = self.current_path
        self._refresh_generation += 1
        generation = self._refresh_generation
        self.folder_status.setText("● Cargando carpeta…")

        if self.tree.topLevelItemCount() == 0:
            self.tree.set_empty_message("Cargando contenido…")

        def work(progress):
            self.connection.ensure()
            with self.connection.lock:
                attrs = self.connection.sftp.listdir_attr(path)
            rows = []
            for a in attrs:
                if a.filename in (".", ".."):
                    continue
                if stat.S_ISDIR(a.st_mode):
                    typ = "d"
                elif stat.S_ISLNK(a.st_mode):
                    typ = "l"
                else:
                    typ = "f"
                rows.append({
                    "name": a.filename,
                    "path": remote_join(path, a.filename),
                    "type": typ,
                    "size": int(a.st_size or 0),
                    "mtime": float(a.st_mtime or 0),
                    "permissions": stat.filemode(a.st_mode),
                    "hidden": a.filename.startswith("."),
                })
            rows.sort(key=lambda r: (0 if r["type"] == "d" else 1, r["name"].casefold()))
            return rows

        self.status_message.emit(f"Listando {path}...")
        w = Worker(work)
        w.signals.finished.connect(
            lambda rows, g=generation, p=path:
                self._display_rows_if_current(g, p, rows)
        )
        w.signals.error.connect(
            lambda error, g=generation, p=path:
                self._refresh_error_if_current(g, p, error)
        )
        self.pool.start(w)

    def _refresh_error_if_current(self, generation, path, error):
        if generation != self._refresh_generation:
            return
        if posixpath.normpath(path) != posixpath.normpath(self.current_path):
            return
        self.show_error(error)

    def _display_rows_if_current(self, generation, path, rows):
        if generation != self._refresh_generation:
            return
        if posixpath.normpath(path) != posixpath.normpath(self.current_path):
            return
        self.display_rows(rows)

    def display_rows(self, rows):
        self._all_rows = rows
        self.path_edit.setText(self.current_path)
        self.tree.set_drop_message(
            f"Suelta aquí para subir a\n{self.current_path}"
        )
        self.apply_filter()

        if rows:
            files = sum(1 for r in rows if r["type"] != "d")
            dirs = sum(1 for r in rows if r["type"] == "d")
            self.folder_status.setText(
                f"● Listo  •  {dirs} carpeta(s)  •  {files} archivo(s)"
            )
            self.tree.set_empty_message("")
        else:
            self.folder_status.setText("● Carpeta vacía")
            self.tree.set_empty_message(
                "Esta carpeta está vacía\n"
                "Arrastra archivos aquí para subirlos"
            )

        self.status_message.emit(f"{len(rows)} elementos • {self.current_path}")

    def _schedule_filter(self, *_):
        self._filter_timer.start()

    def apply_filter(self, *_):
        term = self.filter_edit.text().strip().casefold()
        show_hidden = self.hidden.isChecked()
        self.tree.setUpdatesEnabled(False)
        sorting_enabled = self.tree.isSortingEnabled()
        sort_column = self.tree.header().sortIndicatorSection()
        sort_order = self.tree.header().sortIndicatorOrder()
        self.tree.setSortingEnabled(False)
        try:
            self.tree.clear()
            for row in self._all_rows:
                if not show_hidden and row["hidden"]:
                    continue
                if term and term not in row["name"].casefold():
                    continue
                prefix = (
                    "[D]" if row["type"] == "d"
                    else ("[L]" if row["type"] == "l" else "   ")
                )
                item = QTreeWidgetItem([
                    f"{prefix} {row['name']}",
                    "" if row["type"] == "d" else human_size(row["size"]),
                    fmt_mtime(row["mtime"]),
                    row["permissions"]
                ])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                item.setIcon(0, self._icon_for_remote_row(row))
                item.setToolTip(0, row["path"])
                item.setToolTip(1, human_size(row["size"]))
                item.setToolTip(2, fmt_mtime(row["mtime"]))
                item.setToolTip(3, row["permissions"])
                if row["hidden"]:
                    item.setForeground(0, QColor("#6f7785"))
                self.tree.addTopLevelItem(item)

            if self.tree.topLevelItemCount() == 0:
                if term:
                    self.tree.set_empty_message(
                        f"No hay resultados para “{self.filter_edit.text().strip()}”"
                    )
                elif self._all_rows:
                    self.tree.set_empty_message(
                        "No hay elementos visibles con el filtro actual"
                    )
                else:
                    self.tree.set_empty_message(
                        "Esta carpeta está vacía\n"
                        "Arrastra archivos aquí para subirlos"
                    )
        finally:
            if sorting_enabled:
                self.tree.setSortingEnabled(True)
                self.tree.sortItems(sort_column, sort_order)
            self.tree.setUpdatesEnabled(True)

    def follow_terminal_path(self, path):
        """Sigue OSC 7 silenciosamente y sólo dentro del home SFTP permitido."""
        requested = posixpath.normpath(str(path or ""))
        home = posixpath.normpath(self.effective_home())
        if not requested.startswith("/"):
            return False
        if requested != home and not requested.startswith(home.rstrip("/") + "/"):
            return False
        if posixpath.normpath(self.current_path) == requested:
            return True
        self.set_path(requested)
        return True

    def set_path(self, path):
        requested = posixpath.normpath(path or "/")
        home = posixpath.normpath(
            self.effective_home()
        )

        # Rechazo rápido lexical; la validación definitiva usa realpath SFTP.
        if (
            requested != home
            and not requested.startswith(home.rstrip("/") + "/")
        ):
            QMessageBox.warning(
                self,
                "MobHector",
                f"El navegador está restringido a:\n{home}"
            )
            return

        self._refresh_generation += 1
        generation = self._refresh_generation
        self.folder_status.setText("● Validando ruta…")

        def work(progress):
            self.connection.ensure()
            with self.connection.lock:
                sftp = self.connection.sftp
                canonical_home = posixpath.normpath(
                    sftp.normalize(home)
                )
                canonical_path = posixpath.normpath(
                    sftp.normalize(requested)
                )
                if (
                    canonical_path != canonical_home
                    and not canonical_path.startswith(
                        canonical_home.rstrip("/") + "/"
                    )
                ):
                    raise PermissionError(
                        "La ruta resuelve fuera del home remoto permitido."
                    )
                attr = sftp.stat(canonical_path)

            if not stat.S_ISDIR(attr.st_mode):
                raise RuntimeError("La ruta no es un directorio.")

            return canonical_path

        w = Worker(work)
        w.signals.finished.connect(
            lambda canonical, g=generation:
                self._path_ok_if_current(g, canonical)
        )
        w.signals.error.connect(
            lambda error, g=generation:
                self._path_error_if_current(g, error)
        )
        self.pool.start(w)

    def _path_ok_if_current(self, generation, path):
        if generation != self._refresh_generation:
            return
        self.current_path = path
        self.refresh()

    def _path_error_if_current(self, generation, error):
        if generation != self._refresh_generation:
            return
        self.show_error(error)

    def _path_ok(self, path):
        # Compatibilidad para acciones internas que ya validaron la ruta.
        self.current_path = path
        self.refresh()

    def go_path(self):
        self.set_path(self.path_edit.text().strip())

    def go_home(self):
        self.set_path(self.effective_home())

    def go_inbox(self):
        inbox = self.effective_inbox()
        if not inbox:
            return

        def work(progress):
            sftp = self.connection.open_sftp_session()
            try:
                ensure_remote_directory(sftp, inbox)

                canonical_home = posixpath.normpath(
                    sftp.normalize(
                        self.effective_home()
                    )
                )
                canonical_inbox = posixpath.normpath(
                    sftp.normalize(inbox)
                )

                if (
                    canonical_inbox != canonical_home
                    and not canonical_inbox.startswith(
                        canonical_home.rstrip("/") + "/"
                    )
                ):
                    raise PermissionError(
                        "La carpeta de envíos resuelve fuera del home remoto."
                    )

                info = sftp.stat(canonical_inbox)
                if not stat.S_ISDIR(info.st_mode):
                    raise RuntimeError(
                        "La carpeta de envíos no es un directorio."
                    )

                return canonical_inbox
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass

        w = Worker(work)
        w.signals.finished.connect(self._path_ok)
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def go_up(self):
        home = posixpath.normpath(self.effective_home())
        current = posixpath.normpath(self.current_path)
        if current == home:
            return
        p = posixpath.dirname(current)
        if p != home and not p.startswith(home.rstrip("/") + "/"):
            p = home
        self.set_path(p)

    def open_item(self, item, column):
        row = item.data(0, Qt.ItemDataRole.UserRole)
        if not row:
            return
        if row["type"] == "d":
            self.set_path(row["path"])
        elif row["type"] == "f" and is_text_candidate(row["name"], row["size"]):
            self.open_editor.emit(row["path"])
        else:
            self.properties(row)

    def context_menu(self, pos):
        rows = self.selected_rows()
        one = rows[0] if len(rows) == 1 else None
        is_dir = bool(
            one and one.get("type") == "d"
        )
        is_file = bool(
            one and one.get("type") == "f"
        )
        is_text = bool(
            is_file
            and is_text_candidate(
                one.get("name", ""),
                int(one.get("size", 0) or 0)
            )
        )

        menu = QMenu(self)

        open_a = menu.addAction("Abrir / Entrar")
        open_a.setEnabled(one is not None)

        terminal_here_a = menu.addAction(
            "Abrir terminal aquí"
        )
        terminal_here_a.setEnabled(is_dir)

        vim_a = menu.addAction(
            "Abrir archivo con Vim en terminal"
        )
        vim_a.setEnabled(is_file)

        edit_a = menu.addAction(
            "Editar texto (editor integrado)"
        )
        edit_a.setEnabled(is_text)

        menu.addSeparator()

        download_a = menu.addAction("Descargar")
        download_a.setEnabled(bool(rows))

        rename_a = menu.addAction("Renombrar")
        rename_a.setEnabled(one is not None)

        chmod_a = menu.addAction("Permisos chmod")
        chmod_a.setEnabled(one is not None)

        delete_a = menu.addAction("Eliminar")
        delete_a.setEnabled(bool(rows))

        menu.addSeparator()

        copy_a = menu.addAction("Copiar ruta")
        copy_a.setEnabled(one is not None)

        prop_a = menu.addAction("Propiedades")
        prop_a.setEnabled(one is not None)

        refresh_a = menu.addAction("Actualizar")

        chosen = menu.exec(
            self.tree.viewport().mapToGlobal(pos)
        )

        if chosen == open_a and one:
            self.open_item(
                self.tree.selectedItems()[0],
                0
            )

        elif chosen == terminal_here_a and is_dir:
            self.open_terminal_here.emit(
                one["path"]
            )

        elif chosen == vim_a and is_file:
            self.open_vim.emit(
                one["path"]
            )

        elif chosen == edit_a and is_text:
            self.open_editor.emit(
                one["path"]
            )

        elif chosen == download_a:
            self.download_selected()

        elif chosen == rename_a and one:
            self.rename(one)

        elif chosen == chmod_a and one:
            self.chmod(one)

        elif chosen == delete_a and rows:
            self.delete_rows(rows)

        elif chosen == copy_a and one:
            QApplication.clipboard().setText(
                one["path"]
            )

        elif chosen == prop_a and one:
            self.properties(one)

        elif chosen == refresh_a:
            self.refresh()

    def show_transfer_queue(self):
        self.transfers.show()
        self.transfers.raise_()

    def update_selection_status(self):
        rows = self.selected_rows()
        count = len(rows)
        total = sum(r.get("size", 0) for r in rows if r.get("type") != "d")
        dirs = sum(1 for r in rows if r.get("type") == "d")
        files = count - dirs

        if not rows:
            self.selection_status.setText("0 seleccionados")
            return

        parts = [f"{count} seleccionado(s)"]
        if dirs:
            parts.append(f"{dirs} carpeta(s)")
        if files:
            parts.append(f"{files} archivo(s)")
        if total:
            parts.append(human_size(total))
        self.selection_status.setText("  •  ".join(parts))

    def rename_selected_shortcut(self):
        rows = self.selected_rows()
        if len(rows) == 1:
            self.rename(rows[0])

    def delete_selected_shortcut(self):
        rows = self.selected_rows()
        if rows:
            self.delete_rows(rows)

    def _drag_state_changed(self, active):
        if active:
            self.folder_status.setText(
                f"↓ Suelta los archivos para subirlos a {self.current_path}"
            )
        else:
            if self._all_rows:
                files = sum(1 for r in self._all_rows if r["type"] != "d")
                dirs = sum(1 for r in self._all_rows if r["type"] == "d")
                self.folder_status.setText(
                    f"● Listo  •  {dirs} carpeta(s)  •  {files} archivo(s)"
                )
            else:
                self.folder_status.setText("● Carpeta vacía")

    def _activity_begin(self, tid, direction, label, destination):
        LOGGER.info("Transfer begin tid=%s direction=%s label=%s destination=%s", tid, direction, label, destination)
        self.current_activity_tid = tid
        self._activity_hide_token += 1

        is_upload = str(direction).upper().startswith("SUB")
        self.activity_icon.setText("⇧" if is_upload else "⇩")
        self.activity_title.setText(
            "WINDOWS → SERVIDOR  •  SUBIENDO"
            if is_upload
            else "SERVIDOR → WINDOWS  •  DESCARGANDO"
        )
        self.activity_file.setText(label)
        self.activity_percent.setText("Preparando…")
        self.activity_detail.setText("Calculando transferencia…")
        self.activity_destination.setText(destination)

        self.activity_bar.setRange(0, 0)
        self.activity_bar.setValue(0)
        self.activity_bar.setFormat("Preparando…")

        self.activity_frame.show()
        self.activity_frame.raise_()
        self.activity_frame.updateGeometry()
        self.updateGeometry()

        # Qt la pintará en el siguiente ciclo del event loop; evitamos
        # processEvents() porque puede reentrar acciones del usuario.
        self.folder_status.setText("● Preparando transferencia…")

    def _activity_progress(self, tid, payload):
        if tid != self.current_activity_tid:
            return

        stage = payload.get("stage", "transferring")
        detail = payload.get("detail", "")
        percent = max(0, min(100, int(payload.get("percent", 0) or 0)))

        if stage == "preparing":
            self.activity_bar.setRange(0, 0)
            self.activity_bar.setFormat("Preparando…")
            self.activity_percent.setText("Preparando…")
            self.activity_detail.setText(
                detail or "Calculando tamaño y preparando transferencia…"
            )
            return

        meta = transfer_meta(
            payload.get("bytes_done", 0),
            payload.get("bytes_total", 0),
            payload.get("speed", 0),
        )

        if stage == "complete":
            # Fallback de finalización robusto: complete viene del motor tras
            # cerrar/verificar el archivo, no de un simple cálculo porcentual.
            self.activity_bar.setRange(0, 100)
            self.activity_bar.setValue(100)
            self.activity_bar.setFormat("100%")
            self.activity_percent.setText("100%")
            self.activity_icon.setText("✓")
            self.activity_title.setText("TRANSFERENCIA COMPLETADA")
            if detail:
                self.activity_file.setText(detail)
            self.activity_detail.setText(meta or "Completado")
            self.folder_status.setText("● Transferencia completada")

            # Si finished() no llegara por cualquier razón, la tarjeta no
            # queda congelada: se oculta sola tras mostrar el resultado.
            self._activity_hide_token += 1
            token = self._activity_hide_token
            def hide_completed_fallback():
                if token == self._activity_hide_token:
                    self.activity_frame.hide()
            QTimer.singleShot(6500, hide_completed_fallback)
            return

        if self.activity_bar.minimum() == 0 and self.activity_bar.maximum() == 0:
            self.activity_bar.setRange(0, 100)

        percent = max(0, min(99, percent))
        self.activity_bar.setValue(percent)
        self.activity_bar.setFormat(f"{percent}%")
        self.activity_percent.setText(f"{percent}%")

        if detail:
            self.activity_file.setText(detail)

        self.activity_detail.setText(meta or "Transfiriendo…")
        self.folder_status.setText(
            f"● Transferencia en curso  •  {percent}%"
        )

    def _activity_finish(self, tid, ok, text):
        LOGGER.info("Transfer finish tid=%s ok=%s detail=%s", tid, ok, text)
        if tid != self.current_activity_tid:
            return

        self.activity_bar.setRange(0, 100)

        if ok:
            self.activity_bar.setValue(100)
            self.activity_bar.setFormat("100%")
            self.activity_percent.setText("100%")
            self.activity_icon.setText("✓")
            self.activity_title.setText("TRANSFERENCIA COMPLETADA")
            self.activity_detail.setText(text)
            self.folder_status.setText("● Transferencia completada")
        else:
            self.activity_bar.setValue(0)
            self.activity_bar.setFormat("Error")
            self.activity_percent.setText("ERROR")
            self.activity_icon.setText("✕")
            self.activity_title.setText("ERROR DE TRANSFERENCIA")
            self.activity_detail.setText(text)
            self.folder_status.setText("● Error de transferencia")

        self._activity_hide_token += 1
        token = self._activity_hide_token

        def hide_if_current():
            if token != self._activity_hide_token:
                return
            self.activity_frame.hide()
            if self._all_rows:
                files = sum(1 for r in self._all_rows if r["type"] != "d")
                dirs = sum(1 for r in self._all_rows if r["type"] == "d")
                self.folder_status.setText(
                    f"● Listo  •  {dirs} carpeta(s)  •  {files} archivo(s)"
                )
            else:
                self.folder_status.setText("● Carpeta vacía")

        # Mantener el resultado visible para que el usuario alcance a verlo.
        QTimer.singleShot(6000 if ok else 10000, hide_if_current)

    def _handle_transfer_progress(self, tid, payload):
        stage = payload.get("stage", "transferring")
        percent = payload.get("percent", 0)
        detail = payload.get("detail", "")
        meta = transfer_meta(
            payload.get("bytes_done", 0),
            payload.get("bytes_total", 0),
            payload.get("speed", 0),
        )

        self.transfers.update_transfer(
            tid,
            percent=percent,
            detail=detail,
            stage=stage,
            meta=meta,
        )
        self._activity_progress(tid, payload)

    def show_error(self, error):
        self.status_message.emit("Error SFTP")
        self.folder_status.setText("● Error SFTP")
        QMessageBox.critical(
            self,
            "SFTP",
            compact_error(error)
        )

    def _remember_transfer_worker(self, tid, worker):
        self._transfer_workers[tid] = worker

    def _release_transfer_worker(self, tid):
        self._transfer_workers.pop(tid, None)
        self.transfers.cancel_events.pop(tid, None)

    def _finish_upload_worker(self, tid, result):
        try:
            self._upload_done(tid, result)
        finally:
            self._release_transfer_worker(tid)

    def _finish_download_worker(self, tid, result):
        try:
            self._download_done(tid, result)
        finally:
            self._release_transfer_worker(tid)

    def _fail_transfer_worker(self, tid, error):
        try:
            self._transfer_error(tid, error)
        finally:
            self._release_transfer_worker(tid)

    def choose_upload(self):
        menu = QMenu(self)
        files = menu.addAction("Archivos...")
        folder = menu.addAction("Carpeta completa...")
        choice = menu.exec(self.mapToGlobal(self.rect().center()))
        if choice == files:
            paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar archivos")
            if paths:
                self.upload_paths(paths)
        elif choice == folder:
            path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
            if path:
                self.upload_paths([path])

    def upload_paths(self, paths):
        paths = [
            os.path.abspath(p)
            for p in paths
            if os.path.exists(p)
        ]
        if not paths:
            return

        existing_names = {
            row.get("name")
            for row in self._all_rows
        }
        conflicts = [
            os.path.basename(p.rstrip("\\/"))
            for p in paths
            if os.path.basename(p.rstrip("\\/")) in existing_names
        ]
        if conflicts:
            preview = ", ".join(conflicts[:4])
            if len(conflicts) > 4:
                preview += f" y {len(conflicts) - 4} más"
            answer = QMessageBox.question(
                self,
                "Confirmar reemplazo remoto",
                "Ya existen elementos con el mismo nombre en el servidor:\n"
                f"{preview}\n\n"
                "Los archivos existentes serán reemplazados de forma "
                "atómica y las carpetas se combinarán. ¿Continuar?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        remote_base = self.current_path
        tid = f"up-{time.time_ns()}"
        label = (
            os.path.basename(paths[0].rstrip("\\/")) or paths[0]
            if len(paths) == 1 else f"{len(paths)} elementos"
        )

        self.transfers.start_transfer(tid, "SUBIR", label, remote_base)
        self._activity_begin(tid, "SUBIENDO", label, f"→ {remote_base}")

        cancel_event = threading.Event()
        self.transfers.cancel_events[tid] = cancel_event

        def work(progress):
            return transfer_upload(
                self.connection,
                paths,
                remote_base,
                progress,
                cancel=cancel_event
            )

        w = Worker(work)
        self._remember_transfer_worker(tid, w)
        w.signals.progress.connect(
            lambda payload, transfer_id=tid:
                self._handle_transfer_progress(transfer_id, payload)
        )
        w.signals.finished.connect(
            lambda result, transfer_id=tid:
                self._finish_upload_worker(transfer_id, result)
        )
        w.signals.error.connect(
            lambda error, transfer_id=tid:
                self._fail_transfer_worker(transfer_id, error)
        )
        self.pool.start(w)


    def _upload_done(self, tid, result):
        count = result.get("count", 0) if isinstance(result, dict) else result
        total_bytes = result.get("bytes", 0) if isinstance(result, dict) else 0
        elapsed = result.get("elapsed", 0) if isinstance(result, dict) else 0
        avg_speed = (total_bytes / elapsed) if elapsed else 0

        # El estado final no depende de que haya llegado el último evento
        # progress. Esto corrige archivos pequeños/muy rápidos.
        self._handle_transfer_progress(tid, {
            "stage": "complete",
            "percent": 100,
            "detail": self.activity_file.text() or "Completado",
            "bytes_done": total_bytes,
            "bytes_total": total_bytes,
            "speed": avg_speed,
        })

        detail = f"✓ Completado  •  {count} elemento(s)"
        if total_bytes:
            detail += f"  •  {human_size(total_bytes)}"
        if avg_speed:
            detail += f"  •  Prom. {human_rate(avg_speed)}"

        self.transfers.finish_transfer(tid, True, detail)
        self._activity_finish(tid, True, detail)
        self.refresh()
        self.status_message.emit("Subida completada")
        self.folder_status.setText(
            "● Subida completada correctamente"
        )

    def download_selected(self):
        rows = self.selected_rows()
        if not rows:
            QMessageBox.information(
                self,
                "Descargar",
                "Selecciona archivos o carpetas."
            )
            return

        dest = (
            self.local_browser.current_path
            if self.local_browser
            else safe_local_start()
        )
        conflicts = [
            posixpath.basename(row["path"])
            for row in rows
            if os.path.exists(
                os.path.join(
                    dest,
                    posixpath.basename(row["path"])
                )
            )
        ]
        if conflicts:
            preview = ", ".join(conflicts[:4])
            if len(conflicts) > 4:
                preview += f" y {len(conflicts) - 4} más"
            answer = QMessageBox.question(
                self,
                "Confirmar reemplazo local",
                "Ya existen elementos en Windows con el mismo nombre:\n"
                f"{preview}\n\n"
                "Los archivos existentes serán reemplazados sólo después "
                "de completar y validar la descarga. ¿Continuar?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.download_rows(rows, dest)

    def download_rows(self, rows, dest):
        if not rows:
            return

        tid = f"down-{time.time_ns()}"
        label = (
            posixpath.basename(rows[0]["path"])
            if len(rows) == 1 else f"{len(rows)} elementos"
        )

        self.transfers.start_transfer(tid, "BAJAR", label, dest)
        self._activity_begin(tid, "DESCARGANDO", label, f"→ {dest}")

        cancel_event = threading.Event()
        self.transfers.cancel_events[tid] = cancel_event

        def work(progress):
            return transfer_download(
                self.connection,
                rows,
                dest,
                progress,
                cancel=cancel_event
            )

        w = Worker(work)
        self._remember_transfer_worker(tid, w)
        w.signals.progress.connect(
            lambda payload, transfer_id=tid:
                self._handle_transfer_progress(transfer_id, payload)
        )
        w.signals.finished.connect(
            lambda result, transfer_id=tid:
                self._finish_download_worker(transfer_id, result)
        )
        w.signals.error.connect(
            lambda error, transfer_id=tid:
                self._fail_transfer_worker(transfer_id, error)
        )
        self.pool.start(w)


    def _download_done(self, tid, result):
        count = result.get("count", 0) if isinstance(result, dict) else result
        total_bytes = result.get("bytes", 0) if isinstance(result, dict) else 0
        elapsed = result.get("elapsed", 0) if isinstance(result, dict) else 0
        avg_speed = (total_bytes / elapsed) if elapsed else 0

        # Forzar 100% desde el hilo principal incluso si la transferencia
        # fue tan rápida que Qt no llegó a pintar eventos intermedios.
        self._handle_transfer_progress(tid, {
            "stage": "complete",
            "percent": 100,
            "detail": self.activity_file.text() or "Completado",
            "bytes_done": total_bytes,
            "bytes_total": total_bytes,
            "speed": avg_speed,
        })

        detail = f"✓ Completado  •  {count} elemento(s)"
        if total_bytes:
            detail += f"  •  {human_size(total_bytes)}"
        if avg_speed:
            detail += f"  •  Prom. {human_rate(avg_speed)}"

        self.transfers.finish_transfer(tid, True, detail)
        self._activity_finish(tid, True, detail)

        if self.local_browser:
            self.local_browser.refresh()

        self.status_message.emit("Descarga completada")
        self.folder_status.setText(
            "● Descarga completada correctamente"
        )

    def _transfer_error(self, tid, error):
        if "TransferCancelled" in str(error):
            self.transfers.finish_transfer(tid, False, "Cancelada; archivos completos conservados")
            self._activity_finish(tid, False, "Transferencia cancelada")
            self.status_message.emit("Transferencia cancelada")
            return
        short_error = "La transferencia no pudo completarse"
        self.transfers.finish_transfer(tid, False, f"✕ {short_error}")
        self._activity_finish(tid, False, short_error)
        self.status_message.emit("Error de transferencia")
        QMessageBox.critical(
            self,
            "Transferencia",
            compact_error(error)
        )

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre:")
        if not ok:
            return
        try:
            name = validate_remote_entry_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Nueva carpeta", str(exc))
            return
        target = remote_join(self.current_path, name)

        def work(progress):
            with self.connection.lock:
                self.connection.sftp.mkdir(target)
            return True

        w = Worker(work)
        w.signals.finished.connect(lambda _: self.refresh())
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def rename(self, row):
        name, ok = QInputDialog.getText(
            self,
            "Renombrar",
            "Nuevo nombre:",
            text=row["name"]
        )
        if not ok:
            return
        try:
            name = validate_remote_entry_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Renombrar", str(exc))
            return
        if name == row["name"]:
            return
        target = remote_join(
            posixpath.dirname(row["path"]),
            name
        )

        def work(progress):
            with self.connection.lock:
                self.connection.sftp.rename(row["path"], target)
            return True

        w = Worker(work)
        w.signals.finished.connect(lambda _: self.refresh())
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def chmod(self, row):
        value, ok = QInputDialog.getText(
            self, "chmod", "Modo octal:",
            text="755" if row["type"] == "d" else "644"
        )
        if not ok:
            return
        if not re.fullmatch(r"[0-7]{3,4}", value.strip()):
            QMessageBox.warning(self, "chmod", "Modo octal no válido.")
            return
        mode = int(value.strip(), 8)

        def work(progress):
            with self.connection.lock:
                self.connection.sftp.chmod(row["path"], mode)
            return True

        w = Worker(work)
        w.signals.finished.connect(lambda _: self.refresh())
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def delete_rows(self, rows):
        names = "\n".join("• " + r["name"] for r in rows[:12])
        answer = QMessageBox.warning(
            self, "Eliminar",
            f"Se eliminarán permanentemente:\n\n{names}\n\n¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def work(progress):
            sftp = self.connection.open_sftp_session()
            try:
                def remove_path(path):
                    a = sftp.lstat(path)
                    if stat.S_ISDIR(a.st_mode) and not stat.S_ISLNK(a.st_mode):
                        for child in sftp.listdir_attr(path):
                            if child.filename not in (".", ".."):
                                remove_path(remote_join(path, child.filename))
                        sftp.rmdir(path)
                    else:
                        sftp.remove(path)

                for row in rows:
                    remove_path(row["path"])
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass
            return True

        w = Worker(work)
        w.signals.finished.connect(lambda _: self.refresh())
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def properties(self, row):
        def work(progress):
            with self.connection.lock:
                a = self.connection.sftp.lstat(row["path"])
            return (
                f"Nombre: {row['name']}\n"
                f"Ruta: {row['path']}\n"
                f"Tamaño: {human_size(a.st_size)} ({a.st_size} bytes)\n"
                f"Permisos: {stat.filemode(a.st_mode)}\n"
                f"UID: {a.st_uid}\nGID: {a.st_gid}\n"
                f"Modificado: {fmt_mtime(a.st_mtime)}"
            )

        w = Worker(work)
        w.signals.finished.connect(lambda t: QMessageBox.information(self, "Propiedades", t))
        w.signals.error.connect(self.show_error)
        self.pool.start(w)

    def search(self):
        dlg = SearchDialog(self.connection, self.effective_home(), self.pool, self)
        dlg.download_requested.connect(
            lambda rows: self.download_rows(
                rows, self.local_browser.current_path if self.local_browser else safe_local_start()
            )
        )
        dlg.exec()


# ============================================================
# Session side panel
# ============================================================

class SessionSidePanel(QTabWidget):
    def __init__(self, connection, session, pool, transfers, local_path, parent=None):
        super().__init__(parent)
        self.remote = RemoteBrowser(connection, session, pool, transfers)
        self.local = LocalBrowser(local_path)
        self.remote.set_local_browser(self.local)
        self.local.upload_requested.connect(self.remote.upload_paths)
        self.addTab(self.remote, "SFTP")
        self.addTab(self.local, "Windows")


# ============================================================
# Terminal session central tab
# ============================================================

class SessionTerminal(QWidget):
    """Pestaña SSH central con reconexión in-place y banner R/Q."""
    editor_requested = Signal(object, str, str)
    status_message = Signal(str)
    files_toggle_requested = Signal()
    reconnect_requested = Signal()
    close_requested = Signal()
    startup_command_changed = Signal(str)

    def __init__(
        self,
        session,
        connection,
        pool,
        transfers,
        local_path,
        terminal_zoom,
        files_visible=True,
        files_width=455,
        appearance_mode="dark",
        terminal_theme="follow",
        background_image="",
        background_blur=18,
        glass_darkness=68,
        clipboard_preferences=None,
        terminal_preferences=None,
        parent=None
    ):
        super().__init__(parent)
        self.setObjectName("sessionWorkspace")
        self.session = session
        self.connection = connection
        self.pool = pool
        self.transfers = transfers
        self._connection_state = "connected"

        self._auto_reconnect_enabled = bool(session.get("_auto_reconnect", False))
        self._auto_reconnect_total = max(
            1, min(10, int(session.get("_auto_reconnect_attempts", 3)))
        )
        self._auto_reconnect_left = self._auto_reconnect_total
        self._auto_reconnect_delay = max(
            1, min(60, int(session.get("_auto_reconnect_delay", 3)))
        )
        self._auto_reconnect_timer = QTimer(self)
        self._auto_reconnect_timer.setSingleShot(True)
        self._auto_reconnect_timer.timeout.connect(self._auto_reconnect_fire)

        self.files_visible = bool(files_visible)
        self.last_files_width = max(300, int(files_width or 455))

        # Glass de terminal es independiente del tema de toda la app.
        self._terminal_glass_image = str(background_image or "")
        self._terminal_glass_blur = max(
            0, min(50, int(background_blur or 0))
        )
        self._terminal_glass_darkness = max(
            0, min(92, int(glass_darkness or 0))
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        info = QFrame()
        info.setObjectName("terminalHeader")
        hl = QHBoxLayout(info)
        hl.setContentsMargins(10, 5, 10, 5)

        self.connection_dot = QLabel("●")
        self.connection_dot.setObjectName("connectedDot")
        hl.addWidget(self.connection_dot)

        title = QLabel(
            f"{session['username']}@{session['host']}:{session.get('port',22)}"
        )
        title.setObjectName("sessionTitle")
        hl.addWidget(title)

        if (
            session.get("auth_mode") == "platon_none"
            and session.get("_platon_jump_enabled")
        ):
            outer_note = QLabel(
                "vía "
                + str(
                    session.get(
                        "_platon_outer_username",
                        "Platon"
                    )
                )
            )
            outer_note.setObjectName("muted")
            outer_note.setToolTip(
                "Usuario temporal externo de Platon; la terminal cambia con su -"
            )
            hl.addWidget(outer_note)

        auth_mode = session.get("auth_mode")

        if auth_mode == "platon_none":
            if session.get("_platon_jump_enabled"):
                auth_text = (
                    "⚡ Platon → su"
                    " • SFTP Platon"
                )
            else:
                auth_text = "⚡ Platon"
        else:
            if auth_mode not in ("key", "password"):
                auth_mode = (
                    "key"
                    if session.get("key_file")
                    else "password"
                )

            auth_text = (
                "🔑 llave"
                if auth_mode == "key"
                else "🔐 contraseña"
            )
        self.auth_badge = QLabel(auth_text)
        self.auth_badge.setObjectName("authBadge")
        hl.addWidget(self.auth_badge)

        hl.addStretch()

        self.startup_button = QPushButton()
        self.startup_button.setToolTip(
            "Abrir o modificar el Startup Command de esta sesión"
        )
        self.startup_button.clicked.connect(self.edit_startup_command)
        self._update_startup_button_state()
        hl.addWidget(self.startup_button)

        files_btn = QPushButton("Archivos")
        files_btn.setToolTip("Mostrar/ocultar SFTP / Archivos")
        files_btn.clicked.connect(self.files_toggle_requested.emit)
        hl.addWidget(files_btn)

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setObjectName("terminalZoomButton")
        self.zoom_out_button.setFixedWidth(34)
        self.zoom_out_button.setToolTip("Alejar terminal (Ctrl+-)")
        self.zoom_out_button.clicked.connect(
            lambda: self.terminal.zoom_out_custom()
        )
        hl.addWidget(self.zoom_out_button)

        self.zoom_label = QLabel(f"{terminal_zoom}%")
        self.zoom_label.setObjectName("muted")
        self.zoom_label.setMinimumWidth(46)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setToolTip("Doble clic no aplica; Ctrl+0 restablece a 100%")
        hl.addWidget(self.zoom_label)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("terminalZoomButton")
        self.zoom_in_button.setFixedWidth(34)
        self.zoom_in_button.setToolTip("Acercar terminal (Ctrl++)")
        self.zoom_in_button.clicked.connect(
            lambda: self.terminal.zoom_in_custom()
        )
        hl.addWidget(self.zoom_in_button)

        self.zoom_reset_button = QPushButton("100%")
        self.zoom_reset_button.setObjectName("terminalZoomResetButton")
        self.zoom_reset_button.setToolTip("Restablecer zoom del terminal")
        self.zoom_reset_button.clicked.connect(
            lambda: self.terminal.zoom_reset_custom()
        )
        hl.addWidget(self.zoom_reset_button)
        lay.addWidget(info)

        # Banner visible además del mensaje dentro de xterm.
        self.disconnect_banner = QFrame()
        self.disconnect_banner.setObjectName("disconnectBanner")
        banner_lay = QHBoxLayout(self.disconnect_banner)
        banner_lay.setContentsMargins(12, 7, 10, 7)
        banner_lay.setSpacing(8)

        self.disconnect_text = QLabel("Conexión SSH interrumpida")
        self.disconnect_text.setObjectName("disconnectText")
        self.disconnect_text.setWordWrap(True)
        banner_lay.addWidget(self.disconnect_text, 1)

        self.retry_button = QPushButton("R  Reintentar")
        self.retry_button.setObjectName("reconnectButton")
        self.retry_button.clicked.connect(self.request_reconnect)
        banner_lay.addWidget(self.retry_button)

        self.close_button = QPushButton("Q  Cerrar pestaña")
        self.close_button.setObjectName("disconnectCloseButton")
        self.close_button.clicked.connect(self.request_close)
        banner_lay.addWidget(self.close_button)

        self.disconnect_banner.hide()
        lay.addWidget(self.disconnect_banner)

        self.terminal_frame = QFrame()
        self.terminal_frame.setObjectName("terminalContainer")
        terminal_lay = QVBoxLayout(self.terminal_frame)
        terminal_lay.setContentsMargins(0, 0, 0, 0)
        terminal_lay.setSpacing(0)

        self.terminal = TerminalWidget(
            connection,
            terminal_zoom,
            clipboard_preferences=clipboard_preferences,
            terminal_preferences=terminal_preferences
        )
        self.terminal.status_message.connect(self.status_message)
        self.terminal.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{z}%")
        )
        self.terminal.connection_lost.connect(self._on_connection_lost)
        self.terminal.reconnect_requested.connect(self.request_reconnect)
        self.terminal.close_requested.connect(self.request_close)
        self.terminal.directory_changed.connect(self._follow_terminal_directory)

        # Backdrop exclusivo del área de terminal.
        #
        # Antes, "Sólo terminal: Glass" hacía transparente xterm.js pero
        # debajo seguía estando el panel opaco del tema de la aplicación.
        # Este backdrop permite que la imagen Glass exista solamente detrás
        # del terminal, sin volver Glass el resto de MobHector.
        self.terminal_backdrop = BackdropWidget()
        self.terminal_backdrop.setObjectName("terminalGlassBackdrop")
        self.terminal_backdrop.set_content(self.terminal)

        terminal_lay.addWidget(self.terminal_backdrop, 1)
        lay.addWidget(self.terminal_frame, 1)

        self.side_panel = SessionSidePanel(
            connection, session, pool, transfers, local_path
        )
        self.side_panel.setObjectName("sessionFilesPanel")
        self.side_panel.setMinimumWidth(320)
        self.side_panel.remote.open_editor.connect(
            lambda path: self.editor_requested.emit(
                connection,
                path,
                posixpath.basename(path)
            )
        )
        self.side_panel.remote.open_terminal_here.connect(
            self.open_terminal_in_directory
        )
        self.side_panel.remote.open_vim.connect(
            self.open_path_with_vim
        )
        self.side_panel.remote.status_message.connect(
            self.status_message
        )

        # Segundo detector: también descubre conexiones TCP/transport caídas
        # aunque el PTY todavía no haya generado recv/error.
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(
            max(
                2000,
                int(session.get("_ssh_health_interval", 5)) * 1000
            )
        )
        self.health_timer.timeout.connect(self._health_check)
        self.health_timer.start()

        self.set_visual_mode(
            appearance_mode,
            terminal_theme,
            background_image=background_image,
            background_blur=background_blur,
            glass_darkness=glass_darkness,
        )
        self.terminal.start()
        self.side_panel.remote.refresh()
        if str(self.session.get("startup_command", "")).strip():
            QTimer.singleShot(900, self._run_startup_command)

    def _update_startup_button_state(self):
        if not hasattr(self, "startup_button"):
            return
        enabled = bool(str(self.session.get("startup_command", "")).strip())
        self.startup_button.setText("Inicio ●" if enabled else "Inicio")

    def edit_startup_command(self):
        current = str(self.session.get("startup_command", "") or "")
        value, ok = QInputDialog.getMultiLineText(
            self,
            "Startup Command",
            "Comando o bloque que se ejecutará una vez al conectar.\n"
            "Déjalo vacío para desactivarlo:",
            current,
        )
        if not ok:
            return
        value = str(value or "").strip()[:12000]
        self.session["startup_command"] = value
        self._update_startup_button_state()
        self.startup_command_changed.emit(value)
        if value:
            self.status_message.emit(
                "Startup Command guardado; se ejecutará en la próxima conexión"
            )
        else:
            self.status_message.emit("Startup Command desactivado")

    def _follow_terminal_directory(self, path):
        if not bool(self.session.get("_sftp_follow_terminal_folder", True)):
            return
        try:
            if self.side_panel.remote.follow_terminal_path(path):
                self.status_message.emit(f"SFTP siguiendo terminal: {path}")
        except Exception:
            LOGGER.debug("OSC 7 ignorado por SFTP", exc_info=True)

    def _run_startup_command(self):
        command = str(self.session.get("startup_command", "")).strip()
        if command and self._connection_state == "connected":
            self.terminal.send_session_command(command, focus=False)
            self.status_message.emit("Comando de inicio ejecutado en esta sesión")

    @Slot(str)
    def _on_connection_lost(self, reason):
        if self._connection_state == "reconnecting":
            return
        self._connection_state = "disconnected"
        self.connection_dot.setStyleSheet("color:#ff6868;")
        self.disconnect_text.setText(
            f"SSH desconectado — {compact_error(reason)}  •  "
            "Presiona R para reintentar o Q para cerrar esta pestaña."
        )
        self.retry_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.disconnect_banner.show()
        self._schedule_auto_reconnect()

    def _schedule_auto_reconnect(self):
        if (
            not self._auto_reconnect_enabled
            or self._auto_reconnect_left <= 0
            or self._connection_state != "disconnected"
        ):
            return

        attempt = self._auto_reconnect_total - self._auto_reconnect_left + 1
        self.disconnect_text.setText(
            f"SSH desconectado • reintento automático "
            f"{attempt}/{self._auto_reconnect_total} en "
            f"{self._auto_reconnect_delay}s • "
            "R: reintentar ahora / Q: cerrar"
        )
        self._auto_reconnect_timer.start(self._auto_reconnect_delay * 1000)

    def _auto_reconnect_fire(self):
        if self._connection_state != "disconnected":
            return
        if self._auto_reconnect_left <= 0:
            return
        self._auto_reconnect_left -= 1
        self.reconnect_requested.emit()

    def _health_check(self):
        if self._connection_state != "connected":
            return
        if not self.connection.is_alive():
            self.terminal.notify_connection_lost(
                "La conexión SSH dejó de responder o el transporte fue cerrado."
            )

    def request_reconnect(self):
        if self._connection_state == "reconnecting":
            return
        self._auto_reconnect_timer.stop()
        self.reconnect_requested.emit()

    def request_close(self):
        self.close_requested.emit()

    def begin_reconnect(self):
        self._connection_state = "reconnecting"
        self.connection_dot.setStyleSheet("color:#f2c94c;")
        self.disconnect_text.setText(
            f"Reintentando {self.session['username']}@{self.session['host']}…"
        )
        self.retry_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self.disconnect_banner.show()
        self.terminal.begin_reconnect()

    def reconnect_success(self):
        self._auto_reconnect_timer.stop()
        self._auto_reconnect_left = self._auto_reconnect_total
        self._connection_state = "connected"
        self.connection_dot.setStyleSheet("color:#4dd68a;")
        self.disconnect_banner.hide()
        self.terminal.reconnect_success()
        QTimer.singleShot(450, self.side_panel.remote.refresh)
        if str(self.session.get("startup_command", "")).strip():
            QTimer.singleShot(900, self._run_startup_command)
        self.status_message.emit(
            f"Reconectado a {self.session['username']}@{self.session['host']}"
        )

    def reconnect_failed(self, reason):
        self._connection_state = "disconnected"
        self.connection_dot.setStyleSheet("color:#ff6868;")
        summary = compact_error(reason)
        self.disconnect_text.setText(
            f"No fue posible reconectar — {summary}  •  R: reintentar / Q: cerrar"
        )
        self.retry_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.disconnect_banner.show()
        self.terminal.reconnect_failed(summary)
        self._schedule_auto_reconnect()

    def is_connected(self):
        return self._connection_state == "connected" and self.connection.is_alive()

    def open_terminal_in_directory(self, path):
        """
        Directorio => cd. No se manda a vim y no se propaga a MultiExec.
        """
        path = str(path)
        command = (
            "cd -- "
            + shlex.quote(path)
            + " && printf '\\033]0;%s\\007' "
            + shlex.quote(path)
        )
        self.terminal.send_session_command(
            command
        )

    def open_path_with_vim(self, path):
        """
        Sólo se invoca desde una fila SFTP que ya fue validada como archivo.
        """
        self.terminal.send_session_command(
            "vim -- " + shlex.quote(str(path))
        )

    def set_visual_mode(
        self,
        mode,
        terminal_theme="follow",
        background_image=None,
        background_blur=None,
        glass_darkness=None,
    ):
        self.setProperty("appearanceMode", mode)
        self.style().unpolish(self)
        self.style().polish(self)

        if background_image is not None:
            self._terminal_glass_image = str(background_image or "")
        if background_blur is not None:
            self._terminal_glass_blur = max(
                0, min(50, int(background_blur))
            )
        if glass_darkness is not None:
            self._terminal_glass_darkness = max(
                0, min(92, int(glass_darkness))
            )

        resolved_terminal = (
            mode if terminal_theme in (None, "", "follow")
            else terminal_theme
        )

        terminal_is_glass = (
            str(resolved_terminal or "").lower() == "glass"
        )
        app_is_glass = str(mode or "").lower() == "glass"
        needs_private_glass = (
            terminal_is_glass
            and not app_is_glass
        )

        try:
            # xterm/QWebEngine se vuelve realmente transparente.
            self.terminal.set_visual_mode(resolved_terminal)

            # Y ahora hay una imagen/capa Glass exclusiva debajo de xterm,
            # aunque la aplicación completa continúe Dark/Light/Coffee/etc.
            self.terminal_backdrop.configure(
                "glass" if needs_private_glass else "dark",
                self._terminal_glass_image,
                self._terminal_glass_blur,
                self._terminal_glass_darkness,
            )

            # QSS base puede hacer terminalContainer opaco. Inline style tiene
            # prioridad y evita que tape el backdrop sólo cuando corresponde.
            if terminal_is_glass:
                self.terminal_frame.setStyleSheet(
                    "QFrame#terminalContainer { "
                    "background: transparent; border: none; }"
                )
                self.terminal_backdrop.setStyleSheet(
                    "background: transparent;"
                )
                self.terminal_backdrop.refresh_after_session_open()
            else:
                self.terminal_frame.setStyleSheet("")
                self.terminal_backdrop.setStyleSheet("")

        except Exception:
            LOGGER.exception("No se pudo aplicar el modo visual al terminal")

    def toggle_files_panel(self):
        self.files_toggle_requested.emit()

    def set_files_visible(self, visible, initial=False):
        self.files_visible = bool(visible)

    def current_files_width(self):
        return self.last_files_width

    def reactivate_after_reparent(
        self,
        context="session-reparent",
        focus=False
    ):
        self.setVisible(True)
        self.show()
        self.updateGeometry()
        self.update()
        self.terminal.reactivate_after_reparent(
            context,
            focus=focus
        )

    def close_session(self):
        self._auto_reconnect_timer.stop()
        self.health_timer.stop()
        self.terminal.close_terminal()
        self.connection.close(clear_secret=True)



class LocalShellTerminal(QWidget):
    """
    Pestaña local integrada.

    Reutiliza exactamente TerminalWidget/xterm.js; sólo cambia el backend:
    Paramiko PTY -> Windows ConPTY.
    """
    status_message = Signal(str)
    close_requested = Signal()

    def __init__(
        self,
        shell_kind,
        terminal_zoom,
        appearance_mode="dark",
        terminal_theme="follow",
        background_image="",
        background_blur=18,
        glass_darkness=68,
        clipboard_preferences=None,
        terminal_preferences=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("localShellWorkspace")

        self.connection = LocalShellConnection(
            shell_kind
        )
        self.session = dict(
            self.connection.session
        )

        self._terminal_glass_image = str(
            background_image or ""
        )
        self._terminal_glass_blur = max(
            0,
            min(50, int(background_blur or 0))
        )
        self._terminal_glass_darkness = max(
            0,
            min(92, int(glass_darkness or 0))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("terminalHeader")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(
            10, 5, 10, 5
        )

        self.connection_dot = QLabel("●")
        self.connection_dot.setObjectName(
            "connectedDot"
        )
        header_lay.addWidget(
            self.connection_dot
        )

        self.title_label = QLabel(
            f"LOCAL • {self.connection.display_name}"
        )
        self.title_label.setObjectName(
            "sessionTitle"
        )
        header_lay.addWidget(
            self.title_label
        )

        backend_badge = QLabel(
            "Windows ConPTY"
        )
        backend_badge.setObjectName(
            "authBadge"
        )
        header_lay.addWidget(
            backend_badge
        )

        header_lay.addStretch()

        restart_button = QPushButton(
            "Reiniciar"
        )
        restart_button.setToolTip(
            "Reiniciar PowerShell/CMD dentro de esta pestaña"
        )
        restart_button.clicked.connect(
            self.restart_shell
        )
        header_lay.addWidget(
            restart_button
        )

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setObjectName("terminalZoomButton")
        self.zoom_out_button.setFixedWidth(34)
        self.zoom_out_button.setToolTip("Alejar terminal (Ctrl+-)")
        self.zoom_out_button.clicked.connect(
            lambda: self.terminal.zoom_out_custom()
        )
        header_lay.addWidget(self.zoom_out_button)

        self.zoom_label = QLabel(
            f"{terminal_zoom}%"
        )
        self.zoom_label.setObjectName(
            "muted"
        )
        self.zoom_label.setMinimumWidth(46)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_lay.addWidget(
            self.zoom_label
        )

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("terminalZoomButton")
        self.zoom_in_button.setFixedWidth(34)
        self.zoom_in_button.setToolTip("Acercar terminal (Ctrl++)")
        self.zoom_in_button.clicked.connect(
            lambda: self.terminal.zoom_in_custom()
        )
        header_lay.addWidget(self.zoom_in_button)

        self.zoom_reset_button = QPushButton("100%")
        self.zoom_reset_button.setObjectName("terminalZoomResetButton")
        self.zoom_reset_button.setToolTip("Restablecer zoom del terminal")
        self.zoom_reset_button.clicked.connect(
            lambda: self.terminal.zoom_reset_custom()
        )
        header_lay.addWidget(self.zoom_reset_button)

        layout.addWidget(header)

        self.terminal_frame = QFrame()
        self.terminal_frame.setObjectName(
            "terminalContainer"
        )

        terminal_lay = QVBoxLayout(
            self.terminal_frame
        )
        terminal_lay.setContentsMargins(
            0, 0, 0, 0
        )
        terminal_lay.setSpacing(0)

        self.terminal = TerminalWidget(
            self.connection,
            terminal_zoom,
            clipboard_preferences=clipboard_preferences,
            terminal_preferences=terminal_preferences,
        )

        self.terminal.status_message.connect(
            self.status_message
        )
        self.terminal.zoom_changed.connect(
            lambda z:
                self.zoom_label.setText(f"{z}%")
        )
        self.terminal.connection_lost.connect(
            self._on_local_shell_lost
        )
        self.terminal.reconnect_requested.connect(
            self.restart_shell
        )
        self.terminal.close_requested.connect(
            self.close_requested
        )

        self.terminal_backdrop = BackdropWidget()
        self.terminal_backdrop.setObjectName(
            "terminalGlassBackdrop"
        )
        self.terminal_backdrop.set_content(
            self.terminal
        )

        terminal_lay.addWidget(
            self.terminal_backdrop,
            1
        )
        layout.addWidget(
            self.terminal_frame,
            1
        )

        self.set_visual_mode(
            appearance_mode,
            terminal_theme,
            background_image=background_image,
            background_blur=background_blur,
            glass_darkness=glass_darkness,
        )

        self.terminal.start()

    @property
    def display_name(self):
        return self.connection.display_name

    def _on_local_shell_lost(self, reason):
        self.connection_dot.setStyleSheet(
            "color:#f2c94c;"
        )
        self.status_message.emit(
            "Terminal local finalizada — "
            + compact_error(reason)
        )

    def restart_shell(self):
        self.connection_dot.setStyleSheet(
            "color:#f2c94c;"
        )
        self.terminal.begin_reconnect()

        # TerminalWidget cerrará el ConPTY viejo y abrirá otro nuevo.
        QTimer.singleShot(
            40,
            self._restart_shell_now
        )

    def _restart_shell_now(self):
        self.terminal.reconnect_success()
        if self.connection.is_alive():
            self.connection_dot.setStyleSheet(
                "color:#4dd68a;"
            )
            self.status_message.emit(
                f"{self.display_name} reiniciado"
            )

    def is_connected(self):
        return self.connection.is_alive()

    def set_visual_mode(
        self,
        mode,
        terminal_theme="follow",
        background_image=None,
        background_blur=None,
        glass_darkness=None,
    ):
        self.setProperty(
            "appearanceMode",
            mode
        )
        self.style().unpolish(self)
        self.style().polish(self)

        if background_image is not None:
            self._terminal_glass_image = str(
                background_image or ""
            )

        if background_blur is not None:
            self._terminal_glass_blur = max(
                0,
                min(50, int(background_blur))
            )

        if glass_darkness is not None:
            self._terminal_glass_darkness = max(
                0,
                min(92, int(glass_darkness))
            )

        resolved_terminal = (
            mode
            if terminal_theme in (
                None, "", "follow"
            )
            else terminal_theme
        )

        terminal_is_glass = (
            str(
                resolved_terminal or ""
            ).lower()
            == "glass"
        )
        app_is_glass = (
            str(mode or "").lower()
            == "glass"
        )
        needs_private_glass = (
            terminal_is_glass
            and not app_is_glass
        )

        try:
            self.terminal.set_visual_mode(
                resolved_terminal
            )

            self.terminal_backdrop.configure(
                (
                    "glass"
                    if needs_private_glass
                    else "dark"
                ),
                self._terminal_glass_image,
                self._terminal_glass_blur,
                self._terminal_glass_darkness,
            )

            if terminal_is_glass:
                self.terminal_frame.setStyleSheet(
                    "QFrame#terminalContainer { "
                    "background: transparent; "
                    "border: none; }"
                )
                self.terminal_backdrop.setStyleSheet(
                    "background: transparent;"
                )
                self.terminal_backdrop.refresh_after_session_open()
            else:
                self.terminal_frame.setStyleSheet("")
                self.terminal_backdrop.setStyleSheet("")

        except Exception:
            LOGGER.exception(
                "No se pudo aplicar apariencia a Local Shell"
            )

    def reactivate_after_reparent(
        self,
        context="local-shell-selected",
        focus=False,
    ):
        self.setVisible(True)
        self.show()
        self.updateGeometry()
        self.update()
        self.terminal.reactivate_after_reparent(
            context,
            focus=focus
        )

    def close_session(self):
        self.terminal.close_terminal()
        self.connection.close()


# ============================================================
# Home page
# ============================================================

class HomePage(QWidget):
    new_session = Signal()
    connect = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(50, 46, 50, 40)

        title = QLabel("MobHector")
        title.setObjectName("homeTitle")
        lay.addWidget(title)

        sub = QLabel("Terminal SSH central + paneles SFTP/Sesiones acoplables")
        sub.setObjectName("homeSubtitle")
        lay.addWidget(sub)
        lay.addSpacing(30)

        cards = QGridLayout()
        cards.setHorizontalSpacing(16)
        cards.setVerticalSpacing(16)
        cards.addWidget(self.card(
            "Terminal grande",
            "El centro de la aplicación queda dedicado al terminal. Usa F11 o modo Zen para ocupar todavía más espacio.",
            "Conectar",
            self.connect
        ), 0, 0)
        cards.addWidget(self.card(
            "Paneles acoplables",
            "Sesiones y SFTP/Windows pueden acoplarse, separarse, flotar o tabificarse. La terminal conserva el centro.",
            "Nueva sesión",
            self.new_session
        ), 0, 1)
        cards.addWidget(self.card(
            "Zoom dinámico",
            "Ctrl + rueda sobre el terminal, Ctrl + / -, Ctrl+0 y controles de zoom en la barra.",
            "100%",
            None
        ), 1, 0)
        cards.addWidget(self.card(
            "Pestañas",
            "Abre varias conexiones SSH, desacóplalas a otra ventana o usa MultiExec para operarlas a la vez.",
            "Ctrl+Shift+M",
            self.connect
        ), 1, 1)
        lay.addLayout(cards)
        lay.addStretch()

        hint = QLabel(
            "Paneles: Ctrl+Shift+S SFTP  •  Ctrl+Shift+E Sesiones  •  "
            "Ctrl+Shift+J Transferencias  •  Ctrl+Shift+M MultiExec  •  F11 Pantalla completa"
        )
        hint.setObjectName("muted")
        lay.addWidget(hint)

    def card(self, title, body, button_text, signal):
        frame = QFrame()
        frame.setObjectName("homeCard")
        l = QVBoxLayout(frame)
        l.setContentsMargins(20, 20, 20, 20)
        t = QLabel(title); t.setObjectName("cardTitle")
        l.addWidget(t)
        b = QLabel(body); b.setWordWrap(True); b.setObjectName("muted")
        l.addWidget(b)
        l.addStretch()
        btn = QPushButton(button_text)
        if signal:
            btn.clicked.connect(signal.emit)
        else:
            btn.setEnabled(False)
        l.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return frame


# ============================================================
# MultiExec + detachable session tabs
# ============================================================

class MultiExecDialog(QDialog):
    """Selecciona qué terminales SSH/Local entrarán al mosaico MultiExec."""
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = entries
        self.setWindowTitle("Multi-Execution")
        self.resize(520, 500)

        lay = QVBoxLayout(self)
        title = QLabel("⚡ Multi-Execution")
        title.setObjectName("multiExecDialogTitle")
        lay.addWidget(title)

        info = QLabel(
            "Las sesiones seleccionadas se mostrarán simultáneamente. "
            "Cada tecla escrita en una terminal activa se enviará a todas "
            "las demás terminales activas."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        lay.addWidget(info)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        for pos, entry in enumerate(entries):
            tab = entry[1]
            session = tab.session
            if isinstance(tab, LocalShellTerminal):
                identity = (
                    f"LOCAL • {tab.display_name} • "
                    f"{session.get('username', '')}"
                )
            else:
                identity = (
                    f"{session.get('username','')}@"
                    f"{session.get('host','')}"
                )

            item = QListWidgetItem(
                f"{entry[2]}\n{identity}"
            )
            item.setData(Qt.ItemDataRole.UserRole, pos)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)

        tools = QHBoxLayout()
        all_btn = QPushButton("Activar todas")
        none_btn = QPushButton("Ninguna")
        all_btn.clicked.connect(lambda: self.set_all(True))
        none_btn.clicked.connect(lambda: self.set_all(False))
        tools.addWidget(all_btn)
        tools.addWidget(none_btn)
        tools.addStretch()
        lay.addLayout(tools)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Iniciar MultiExec"
        )
        self.buttons.accepted.connect(self.validate_accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def set_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def selected_entries(self):
        selected = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(self.entries[int(item.data(Qt.ItemDataRole.UserRole))])
        return selected

    def validate_accept(self):
        if len(self.selected_entries()) < 2:
            QMessageBox.warning(
                self,
                "Multi-Execution",
                "Selecciona al menos dos terminales."
            )
            return
        self.accept()


class MultiExecTile(QFrame):
    """Terminal SSH/Local real y visible dentro del mosaico MultiExec."""
    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.setObjectName("multiExecTile")
        self.original_index, self.session_widget, self.title = entry
        self.setMinimumSize(360, 240)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        header_widget = QFrame(self)
        header_widget.setObjectName("multiExecTileHeader")
        header_widget.setFixedHeight(34)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(7, 2, 7, 2)
        header.setSpacing(8)

        session = self.session_widget.session
        display_name = session.get("name", self.title).lstrip("● ").strip()
        if isinstance(
            self.session_widget,
            LocalShellTerminal
        ):
            identity = (
                f"{display_name}  •  LOCAL  •  "
                f"{session.get('username','')}"
            )
        else:
            identity = (
                f"{display_name}  •  "
                f"{session.get('username','')}@"
                f"{session.get('host','')}"
            )
        name = QLabel(identity)
        name.setObjectName("multiExecTileTitle")
        header.addWidget(name, 1)

        self.enabled_box = QCheckBox("Activo")
        self.enabled_box.setObjectName("multiExecEnabled")
        self.enabled_box.setChecked(True)
        self.enabled_box.setToolTip(
            "Recibe la entrada sincronizada mientras esté marcado."
        )
        header.addWidget(self.enabled_box)

        lay.addWidget(header_widget, 0)

        # addWidget() cambia el parent del SessionTerminal. Qt lo oculta
        # durante ese cambio, por eso show() es obligatorio después.
        lay.addWidget(self.session_widget, 1)
        self.session_widget.setVisible(True)
        self.session_widget.show()

        QTimer.singleShot(
            0,
            lambda: self.reactivate("multiexec-tile-created")
        )

    def is_enabled(self):
        return self.enabled_box.isChecked()

    def reactivate(self, context="multiexec"):
        self.session_widget.setVisible(True)
        self.session_widget.show()
        self.session_widget.reactivate_after_reparent(
            context,
            focus=False
        )

    def release_session(self):
        self.layout().removeWidget(self.session_widget)
        return self.session_widget


class MultiExecPage(QWidget):
    """
    Mosaico real: terminales SSH/Local existentes se reparentan aquí.
    No son capturas ni espejos; son PTY/ConPTY + xterm vivos.
    """
    stop_requested = Signal()

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setObjectName("multiExecPage")
        self.entries = list(entries)
        self.tiles = []

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        banner = QFrame()
        banner.setObjectName("multiExecBanner")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(10, 7, 10, 7)

        self.banner_label = QLabel(
            f"⚡ MULTI-EXEC ACTIVO  •  {len(entries)} TERMINALES  •  TECLADO SINCRONIZADO"
        )
        self.banner_label.setObjectName("multiExecBannerText")
        bl.addWidget(self.banner_label)
        bl.addStretch()

        all_btn = QPushButton("Todas")
        none_btn = QPushButton("Ninguna")
        stop_btn = QPushButton("Salir MultiExec")
        all_btn.clicked.connect(lambda: self.set_all(True))
        none_btn.clicked.connect(lambda: self.set_all(False))
        stop_btn.clicked.connect(self.stop_requested.emit)
        bl.addWidget(all_btn)
        bl.addWidget(none_btn)
        bl.addWidget(stop_btn)
        root.addWidget(banner)

        grid_host = QWidget()
        grid_host.setObjectName("multiExecGrid")
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        root.addWidget(grid_host, 1)

        n = len(entries)
        columns = 1 if n == 1 else (2 if n <= 4 else 3)
        for pos, entry in enumerate(entries):
            tile = MultiExecTile(entry, grid_host)
            tile.enabled_box.toggled.connect(self.update_banner)
            self.tiles.append(tile)
            self.grid.addWidget(tile, pos // columns, pos % columns)

        for col in range(columns):
            self.grid.setColumnStretch(col, 1)
        rows = (n + columns - 1) // columns
        for row in range(rows):
            self.grid.setRowStretch(row, 1)

        QTimer.singleShot(120, self.activate_all)

    def set_all(self, enabled):
        for tile in self.tiles:
            tile.enabled_box.setChecked(bool(enabled))
        self.update_banner()

    def enabled_tabs(self):
        return [
            tile.session_widget
            for tile in self.tiles
            if tile.is_enabled() and tile.session_widget.is_connected()
        ]

    def update_banner(self):
        active = len(self.enabled_tabs())
        self.banner_label.setText(
            f"⚡ MULTI-EXEC ACTIVO  •  {active}/{len(self.tiles)} ACTIVAS  •  TECLADO SINCRONIZADO"
        )

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.activate_all)
        QTimer.singleShot(120, self.activate_all)
        QTimer.singleShot(350, self.fit_all)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(80, self.fit_all)

    def activate_all(self):
        for tile in self.tiles:
            tile.reactivate("multiexec-page-visible")
        self.update_banner()

    def fit_all(self):
        for tile in self.tiles:
            tile.session_widget.terminal.fit_terminal()

    def release_entries(self):
        result = []
        for tile in self.tiles:
            tab = tile.release_session()
            result.append((tile.original_index, tab, tile.title))
        return result


class DetachableTabBar(QTabBar):
    """
    Tabs SSH arrastrables fuera de la barra.

    Dentro de la barra se conserva el reordenamiento normal de QTabBar.
    Al alejar una pestaña y soltarla, MainWindow recibe el QWidget exacto
    de esa sesión para moverlo a una ventana independiente sin reconectar.
    """
    detach_requested = Signal(object, object)
    detach_preview = Signal(bool, str)

    DETACH_VERTICAL_MARGIN = 52
    DETACH_HORIZONTAL_MARGIN = 95

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_widget = None
        self._drag_title = ""
        self._drag_start_global = QPoint()
        self._detach_ready = False
        self.setMovable(True)

    def _tab_widget(self):
        parent = self.parentWidget()
        return parent if isinstance(parent, QTabWidget) else None

    def _global_tabbar_rect(self):
        return QRect(
            self.mapToGlobal(QPoint(0, 0)),
            self.size()
        )

    def _outside_detach_zone(self, global_pos):
        safe_rect = self._global_tabbar_rect().adjusted(
            -self.DETACH_HORIZONTAL_MARGIN,
            -self.DETACH_VERTICAL_MARGIN,
            self.DETACH_HORIZONTAL_MARGIN,
            self.DETACH_VERTICAL_MARGIN,
        )
        return not safe_rect.contains(global_pos)

    def _set_detach_ready(self, ready):
        ready = bool(ready)
        if ready == self._detach_ready:
            return

        self._detach_ready = ready

        if ready:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.unsetCursor()

        self.detach_preview.emit(
            ready,
            self._drag_title
        )

    def _clear_drag(self):
        self._set_detach_ready(False)
        self._drag_widget = None
        self._drag_title = ""
        self._drag_start_global = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.tabAt(event.position().toPoint())
            tabs = self._tab_widget()

            if index >= 0 and tabs is not None:
                candidate = tabs.widget(index)
                if isinstance(candidate, SessionTerminal):
                    self._drag_widget = candidate
                    self._drag_title = self.tabText(index)
                    self._drag_start_global = (
                        event.globalPosition().toPoint()
                    )
                else:
                    # Inicio/MultiExec/editor pueden reordenarse, pero no
                    # muestran feedback de desacoplar ni crean ventanas.
                    self._clear_drag()
            else:
                self._clear_drag()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # QTabBar mantiene primero su drag horizontal/reorder habitual.
        super().mouseMoveEvent(event)

        if (
            self._drag_widget is None
            or not (
                event.buttons()
                & Qt.MouseButton.LeftButton
            )
        ):
            return

        global_pos = event.globalPosition().toPoint()
        moved = (
            global_pos - self._drag_start_global
        ).manhattanLength()

        if moved < QApplication.startDragDistance():
            self._set_detach_ready(False)
            return

        self._set_detach_ready(
            self._outside_detach_zone(global_pos)
        )

    def mouseReleaseEvent(self, event):
        widget = self._drag_widget
        global_pos = event.globalPosition().toPoint()

        detach = (
            event.button() == Qt.MouseButton.LeftButton
            and widget is not None
            and self._detach_ready
        )

        # Terminar antes cualquier reorder interno de QTabBar.
        super().mouseReleaseEvent(event)

        self._clear_drag()

        if detach:
            QTimer.singleShot(
                0,
                lambda w=widget, p=global_pos:
                    self.detach_requested.emit(w, p)
            )


class DetachedSessionWindow(QMainWindow):
    """Ventana independiente para una terminal SSH/Local desacoplada."""
    reattach_requested = Signal(object, str)
    close_session_requested = Signal(object, str)

    def __init__(self, session_widget, title, owner, parent=None):
        super().__init__(parent)
        self.session_widget = session_widget
        self.tab_title = title
        self.owner = owner
        self._reattaching = False
        self._closing_session = False
        self._owner_closing = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(f"{title} — {APP_NAME} {APP_VERSION}")
        self.resize(1250, 820)
        self.setMinimumSize(800, 520)

        self.backdrop = BackdropWidget()
        self.backdrop.set_content(session_widget)
        self.setCentralWidget(self.backdrop)

        session_widget.setVisible(True)
        session_widget.show()

        tb = QToolBar("Pestaña", self)
        # La toolbar de una ventana desacoplada es independiente de la barra
        # principal. No debe enlazarse al menú de personalización de MainWindow.
        tb.setMovable(True)
        tb.setFloatable(False)
        self.addToolBar(tb)

        reattach = QAction("↩ Reacoplar", self)
        reattach.setShortcut(QKeySequence("Ctrl+Shift+D"))
        reattach.triggered.connect(self.request_reattach)
        tb.addAction(reattach)

        if isinstance(
            session_widget,
            LocalShellTerminal
        ):
            restart = QAction(
                "Reiniciar Local Shell",
                self
            )
            restart.triggered.connect(
                session_widget.restart_shell
            )
            tb.addAction(restart)

            close_session = QAction(
                "Cerrar terminal local",
                self
            )
        else:
            files = QAction(
                "SFTP / Archivos",
                self
            )
            files.triggered.connect(
                owner.toggle_current_files
            )
            tb.addAction(files)

            close_session = QAction(
                "Cerrar sesión SSH",
                self
            )

        close_session.triggered.connect(
            self.request_close_session
        )
        tb.addAction(close_session)

        self.sync_appearance()
        QTimer.singleShot(120, session_widget.terminal.fit_terminal)
        QTimer.singleShot(180, session_widget.terminal.focus_terminal)

    def showEvent(self, event):
        super().showEvent(event)
        self.session_widget.reactivate_after_reparent(
            "detached-window-show",
            focus=True
        )

    def sync_appearance(self):
        mode = self.owner.config.get("appearance_mode", "dark")
        self.backdrop.configure(
            mode,
            self.owner.config.get("background_image", ""),
            self.owner.config.get("background_blur", 18),
            self.owner.config.get("glass_darkness", 68),
        )
        self.session_widget.set_visual_mode(
            mode,
            self.owner.config.get("terminal_theme", "follow"),
            background_image=self.owner.config.get(
                "background_image", ""
            ),
            background_blur=self.owner.config.get(
                "background_blur", 18
            ),
            glass_darkness=self.owner.config.get(
                "glass_darkness", 68
            ),
        )
        self.backdrop.refresh_after_session_open()

    def request_reattach(self):
        self.reattach_requested.emit(self.session_widget, self.tab_title)

    def request_close_session(self):
        kind = (
            "terminal local"
            if isinstance(
                self.session_widget,
                LocalShellTerminal
            )
            else "sesión SSH"
        )

        if QMessageBox.question(
            self,
            "Cerrar terminal",
            f"¿Cerrar definitivamente {kind} {self.tab_title}?"
        ) == QMessageBox.StandardButton.Yes:
            self.close_session_requested.emit(
                self.session_widget,
                self.tab_title
            )

    def take_session_widget(self):
        self._reattaching = True
        try:
            self.backdrop.content.removeWidget(self.session_widget)
        except Exception:
            pass
        return self.session_widget

    def closeEvent(self, event):
        if self._owner_closing or self._closing_session or self._reattaching:
            event.accept()
            return

        # La X de la ventana NO mata el SSH: se comporta como Reattach.
        self.reattach_requested.emit(self.session_widget, self.tab_title)
        event.accept()


# ============================================================
# Main
# ============================================================

class ToolbarCustomizeDialog(QDialog):
    def __init__(self, items, layout, hidden, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personalizar barra de herramientas")
        self.resize(520, 500)
        self._items = {str(item["id"]): dict(item) for item in items}
        hidden = set(str(x) for x in (hidden or []))

        ordered = []
        seen = set()
        for item_id in list(layout or []) + list(self._items.keys()):
            item_id = str(item_id)
            if item_id in self._items and item_id not in seen:
                ordered.append(item_id)
                seen.add(item_id)

        root = QVBoxLayout(self)
        info = QLabel(
            "Marca o desmarca botones para mostrarlos u ocultarlos. "
            "Usa Subir/Bajar para cambiar el orden de la barra."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        root.addWidget(info)

        body = QHBoxLayout()
        self.list = QListWidget()
        for item_id in ordered:
            meta = self._items[item_id]
            row = QListWidgetItem(meta.get("label", item_id))
            row.setData(Qt.ItemDataRole.UserRole, item_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            row.setCheckState(Qt.CheckState.Unchecked if item_id in hidden else Qt.CheckState.Checked)
            self.list.addItem(row)
        body.addWidget(self.list, 1)

        controls = QVBoxLayout()
        up = QPushButton("Subir")
        up.clicked.connect(self.move_up)
        down = QPushButton("Bajar")
        down.clicked.connect(self.move_down)
        all_on = QPushButton("Mostrar todo")
        all_on.clicked.connect(self.show_all)
        compact = QPushButton("Modo compacto")
        compact.clicked.connect(self.apply_compact_preset)
        defaults = QPushButton("Restaurar orden")
        defaults.clicked.connect(self.restore_defaults)
        controls.addWidget(up)
        controls.addWidget(down)
        controls.addSpacing(8)
        controls.addWidget(all_on)
        controls.addWidget(compact)
        controls.addWidget(defaults)
        controls.addStretch(1)
        body.addLayout(controls)
        root.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _swap(self, a, b):
        item = self.list.takeItem(a)
        self.list.insertItem(b, item)
        self.list.setCurrentRow(b)

    def move_up(self):
        row = self.list.currentRow()
        if row > 0:
            self._swap(row, row - 1)

    def move_down(self):
        row = self.list.currentRow()
        if 0 <= row < self.list.count() - 1:
            self._swap(row, row + 1)

    def show_all(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked)

    def apply_compact_preset(self):
        compact_hidden = {"appearance", "zen", "fullscreen", "startup"}
        for i in range(self.list.count()):
            item = self.list.item(i)
            item_id = str(item.data(Qt.ItemDataRole.UserRole))
            item.setCheckState(Qt.CheckState.Unchecked if item_id in compact_hidden else Qt.CheckState.Checked)

    def restore_defaults(self):
        ordered = [
            "new", "quick_connect", "local", "connect", "compose",
            "reconnect", "refresh", "sessions", "sftp", "transfers",
            "multiexec", "search", "recorder", "startup",
            "appearance", "zoom", "zen", "fullscreen"
        ]
        rows = {}
        for i in range(self.list.count()):
            item = self.list.takeItem(0)
            rows[str(item.data(Qt.ItemDataRole.UserRole))] = item
        for item_id in ordered + [k for k in rows if k not in ordered]:
            item = rows.get(item_id)
            if item is not None:
                self.list.addItem(item)
        self.show_all()

    def value(self):
        layout = []
        hidden = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            item_id = str(item.data(Qt.ItemDataRole.UserRole))
            layout.append(item_id)
            if item.checkState() != Qt.CheckState.Checked:
                hidden.append(item_id)
        return layout, hidden


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(
            max(2, min(16, int(self.config.get("worker_threads", 8))))
        )
        LOGGER.setLevel(
            getattr(
                logging,
                str(self.config.get("log_level", "INFO")).upper(),
                logging.INFO
            )
        )
        self.last_session_tab = None
        self.zen_mode = False
        self.ui_zoom = int(self.config.get("ui_zoom", 100))

        self.multi_exec_active = False
        self.multi_exec_page = None
        self.multi_exec_entries = []
        self.detached_windows = {}
        self._app_closing = False
        self._terminal_search_query = ""

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} • {Path(__file__).name}")
        self.setMinimumSize(1150, 720)
        self.resize(1600, 950)

        # Paneles realmente acoplables/flotantes como en una herramienta
        # de administración de terminales.
        self.setDockNestingEnabled(True)
        dock_options = (
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.AllowTabbedDocks
        )
        if self.config.get("animated_docks", True):
            dock_options |= QMainWindow.DockOption.AnimatedDocks
        self.setDockOptions(dock_options)

        self.build_actions()
        self.build_central()
        self.build_session_dock()
        self.build_quick_commands_dock()
        self.build_sftp_dock()
        self.build_transfer_dock()
        self.build_toolbar()
        self.build_statusbar()
        self.build_menus()
        self.load_sessions()
        self.install_global_shortcuts()
        self.restore_ui_state()
        self.apply_general_preferences(initial=True)
        self.tabs.currentChanged.connect(self.current_tab_changed)
        self.current_tab_changed(self.tabs.currentIndex())

    # ---------------- Global shortcuts ----------------

    def install_global_shortcuts(self):
        self.shortcut_zen = QShortcut(QKeySequence("Ctrl+Shift+F11"), self)
        self.shortcut_zen.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_zen.activated.connect(self.toggle_zen)

        self.shortcut_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.shortcut_fullscreen.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_fullscreen.activated.connect(self.toggle_fullscreen)

        # Nunca registrar Esc como ApplicationShortcut: Vim/less/tmux
        # necesitan recibir ESC (0x1B) directamente.
        self.shortcut_local_shell = QShortcut(
            QKeySequence("Ctrl+Shift+L"),
            self
        )
        self.shortcut_local_shell.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self.shortcut_local_shell.activated.connect(
            lambda: self.open_local_shell("powershell")
        )

        self.shortcut_compose = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self.shortcut_compose.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_compose.activated.connect(self.focus_compose_bar)

        self.shortcut_immersive_escape = QShortcut(
            QKeySequence("Ctrl+Shift+Esc"),
            self
        )
        self.shortcut_immersive_escape.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self.shortcut_immersive_escape.activated.connect(
            self.exit_immersive_mode
        )

    def exit_immersive_mode(self):
        if self.zen_mode:
            self.toggle_zen()
        if self.isFullScreen():
            self.showMaximized()
        self.menuBar().show()
        self.main_toolbar.show()
        self.statusBar().show()

    # ---------------- UI build ----------------

    def build_actions(self):
        self.act_new = QAction("Nueva sesión", self)
        self.act_new.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new.triggered.connect(self.new_session)

        self.act_connect = QAction("Conectar", self)
        self.act_connect.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_connect.triggered.connect(self.connect_selected)

        self.act_refresh = QAction("Actualizar SFTP", self)
        self.act_refresh.setShortcut(QKeySequence("F5"))
        self.act_refresh.triggered.connect(self.refresh_current)

        self.act_reconnect = QAction("Reconectar", self)
        self.act_reconnect.setShortcut(QKeySequence("Ctrl+R"))
        self.act_reconnect.triggered.connect(self.reconnect_current)

        self.act_fullscreen = QAction("Pantalla completa", self)
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)

        self.act_zen = QAction("Modo Zen", self)
        self.act_zen.triggered.connect(self.toggle_zen)

        self.act_zoom_in = QAction("+", self)
        self.act_zoom_in.setToolTip("Acercar terminal (Ctrl++)")
        self.act_zoom_in.setShortcut(QKeySequence("Ctrl++"))
        self.act_zoom_in.triggered.connect(self.zoom_terminal_in)

        self.act_zoom_out = QAction("−", self)
        self.act_zoom_out.setToolTip("Alejar terminal (Ctrl+-)")
        self.act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self.act_zoom_out.triggered.connect(self.zoom_terminal_out)

        self.act_zoom_reset = QAction("100%", self)
        self.act_zoom_reset.setToolTip("Restablecer zoom al 100% (Ctrl+0)")
        self.act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_reset.triggered.connect(self.zoom_terminal_reset)

        self.act_multiexec = QAction("⚡ MultiExec", self)
        self.act_multiexec.setCheckable(True)
        self.act_multiexec.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.act_multiexec.triggered.connect(self.toggle_multi_exec)

        self.act_detach = QAction("Desacoplar pestaña", self)
        self.act_detach.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.act_detach.triggered.connect(self.detach_current_session)

        self.act_quick_connect = QAction("⚡ Quick Connect", self)
        self.act_quick_connect.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        self.act_quick_connect.triggered.connect(self.quick_connect)

        self.act_terminal_search = QAction("Buscar en terminal…", self)
        self.act_terminal_search.setShortcut(QKeySequence("Ctrl+F"))
        self.act_terminal_search.triggered.connect(self.search_current_terminal)

        self.act_terminal_search_next = QAction("Buscar siguiente", self)
        self.act_terminal_search_next.setShortcut(QKeySequence("F3"))
        self.act_terminal_search_next.triggered.connect(lambda: self.search_current_terminal_next(False))

        self.act_terminal_search_prev = QAction("Buscar anterior", self)
        self.act_terminal_search_prev.setShortcut(QKeySequence("Shift+F3"))
        self.act_terminal_search_prev.triggered.connect(lambda: self.search_current_terminal_next(True))

        self.act_transcript = QAction("● Recorder", self)
        self.act_transcript.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.act_customize_toolbar = QAction("Personalizar barra…", self)
        self.act_customize_toolbar.triggered.connect(self.customize_toolbar)
        self.act_transcript.triggered.connect(self.toggle_current_transcript)

        self.act_startup_command = QAction("⚙ Startup Command…", self)
        self.act_startup_command.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.act_startup_command.setToolTip(
            "Abrir Startup Command de la sesión SSH activa"
        )
        self.act_startup_command.triggered.connect(
            self.edit_current_startup_command
        )

    def build_central(self):
        self.backdrop = BackdropWidget()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        self.main_tab_bar = DetachableTabBar(self.tabs)
        self.tabs.setTabBar(self.main_tab_bar)

        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)

        self.main_tab_bar.detach_requested.connect(
            self.detach_tab_by_drag
        )
        self.main_tab_bar.detach_preview.connect(
            self.show_detach_preview
        )
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.tabBar().customContextMenuRequested.connect(
            self.tab_context_menu
        )

        self.home = HomePage()
        self.home.new_session.connect(self.new_session)
        self.home.connect.connect(self.connect_selected)
        self.tabs.addTab(self.home, "Inicio")
        self.tabs.tabBar().setTabButton(
            0, self.tabs.tabBar().ButtonPosition.RightSide, None
        )

        self.backdrop.set_content(self.tabs)
        self.setCentralWidget(self.backdrop)
        self.apply_appearance()

    def build_session_dock(self):
        self.sessions_dock = QDockWidget("Sesiones", self)
        self.sessions_dock.setObjectName("SessionsDock")
        self.sessions_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.sessions_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)

        brand = QLabel("MOBHECTOR")
        brand.setObjectName("brand")
        lay.addWidget(brand)

        search = QLineEdit()
        search.setPlaceholderText("Filtrar sesiones...")
        search.textChanged.connect(self.filter_sessions)
        lay.addWidget(search)

        self.session_list = QListWidget()
        self.session_list.itemDoubleClicked.connect(lambda _: self.connect_selected())
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.session_context)
        lay.addWidget(self.session_list, 1)

        self.sessions_dock.setMinimumWidth(340)

        row = QGridLayout()
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(6)

        add = QPushButton("+ SSH")
        add.setToolTip(
            "Crear una nueva sesión SSH"
        )
        add.clicked.connect(
            self.new_session
        )

        platon = QPushButton("⚡ Platon")
        platon.setObjectName(
            "PlatonSessionButton"
        )
        platon.setToolTip(
            "Pegar un comando SSH temporal de Platon y abrir "
            "Terminal + SFTP / Archivos"
        )
        platon.clicked.connect(
            self.new_platon_session
        )

        self.local_shell_button = QToolButton()
        self.local_shell_button.setObjectName(
            "LocalShellButton"
        )
        self.local_shell_button.setText(">_ Local")
        self.local_shell_button.setToolTip(
            "Abrir PowerShell dentro de una pestaña de MobHector"
        )
        self.local_shell_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.local_shell_button.clicked.connect(
            lambda:
                self.open_local_shell("powershell")
        )

        local_shell_menu = QMenu(
            self.local_shell_button
        )

        local_ps = local_shell_menu.addAction(
            "PowerShell"
        )
        local_ps.triggered.connect(
            lambda:
                self.open_local_shell("powershell")
        )

        local_cmd = local_shell_menu.addAction(
            "CMD"
        )
        local_cmd.triggered.connect(
            lambda:
                self.open_local_shell("cmd")
        )

        local_wsl = local_shell_menu.addAction("WSL")
        local_wsl.triggered.connect(lambda: self.open_local_shell("wsl"))

        local_git = local_shell_menu.addAction("Git Bash")
        local_git.triggered.connect(lambda: self.open_local_shell("gitbash"))

        self.local_shell_button.setMenu(
            local_shell_menu
        )

        connect = QPushButton("Conectar")
        connect.clicked.connect(
            self.connect_selected
        )

        row.addWidget(add, 0, 0)
        row.addWidget(platon, 0, 1)
        row.addWidget(
            self.local_shell_button,
            1,
            0
        )
        row.addWidget(connect, 1, 1)
        row.setColumnStretch(0, 1)
        row.setColumnStretch(1, 1)
        lay.addLayout(row)

        self.sessions_dock.setWidget(body)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea,
            self.sessions_dock
        )

    def build_quick_commands_dock(self):
        self.quick_commands_dock = QDockWidget("Snippets / Macros", self)
        self.quick_commands_dock.setWindowTitle("Macros")
        self.quick_commands_dock.setObjectName("QuickCommandsDock")
        self.quick_commands_dock.setMinimumWidth(340)
        self.quick_commands_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        hint = QLabel(
            "Termius / Xshell style • doble clic ejecuta en la terminal actual. "
            "Insertar lleva el snippet a Compose sin ejecutarlo."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.quick_command_list = QListWidget()
        self.quick_command_list.itemDoubleClicked.connect(lambda _: self.execute_selected_quick_command())
        self.quick_command_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_command_list.customContextMenuRequested.connect(self.quick_command_context)
        lay.addWidget(self.quick_command_list, 1)
        row = QHBoxLayout()
        insert = QPushButton("Insertar")
        insert.setToolTip("Cargar en Compose Bar sin ejecutar")
        insert.clicked.connect(self.insert_selected_quick_command)
        run = QPushButton("Ejecutar")
        run.clicked.connect(self.execute_selected_quick_command)
        multi = QPushButton("⚡")
        multi.setToolTip("Ejecutar en terminales activas de MultiExec")
        multi.clicked.connect(self.execute_selected_quick_command_multiexec)
        add = QPushButton("+")
        add.setToolTip("Agregar snippet / macro")
        add.clicked.connect(self.add_quick_command)
        row.addWidget(insert)
        row.addWidget(run, 1)
        row.addWidget(multi)
        row.addWidget(add)
        lay.addLayout(row)
        self.quick_commands_dock.setWidget(body)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.quick_commands_dock)
        self.tabifyDockWidget(self.sessions_dock, self.quick_commands_dock)
        self.sessions_dock.raise_()
        self.load_quick_commands()

    def load_quick_commands(self):
        if not hasattr(self, "quick_command_list"):
            return
        self.quick_command_list.clear()
        for idx, item in enumerate(self.config.get("quick_commands", [])):
            name = str(item.get("name", "Comando"))
            command = str(item.get("command", ""))
            row = QListWidgetItem(name)
            row.setData(Qt.ItemDataRole.UserRole, idx)
            row.setToolTip(command)
            self.quick_command_list.addItem(row)

    def _quick_command_index(self):
        item = self.quick_command_list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_quick_command(self):
        idx = self._quick_command_index()
        commands = self.config.get("quick_commands", [])
        if idx is None or idx < 0 or idx >= len(commands):
            return None
        return commands[idx]

    def insert_selected_quick_command(self):
        item = self._selected_quick_command()
        if not item:
            QMessageBox.information(self, "Snippets", "Selecciona un snippet.")
            return
        command = str(item.get("command", "")).strip()
        if not command:
            return
        self.set_compose_text(command)
        self.status.showMessage(
            f"Snippet cargado en Compose sin ejecutar: {item.get('name','')}", 3000
        )

    def execute_selected_quick_command_multiexec(self):
        item = self._selected_quick_command()
        if not item:
            QMessageBox.information(self, "Snippets", "Selecciona un snippet.")
            return
        self.send_command_multiexec(str(item.get("command", "")), source_label="Snippet")

    def execute_selected_quick_command(self):
        idx = self._quick_command_index()
        if idx is None:
            QMessageBox.information(self, "Comandos rápidos", "Selecciona un comando.")
            return
        commands = self.config.get("quick_commands", [])
        if idx < 0 or idx >= len(commands):
            return
        tab = self.current_terminal_tab()
        if not isinstance(tab, (SessionTerminal, LocalShellTerminal)):
            QMessageBox.information(self, "Comandos rápidos", "Abre o selecciona una terminal primero.")
            return
        command = str(commands[idx].get("command", "")).strip()
        if not command:
            return
        if tab.terminal.send_session_command(command):
            self.status.showMessage(f"Comando rápido ejecutado: {commands[idx].get('name','')}", 2500)

    def add_quick_command(self):
        name, ok = QInputDialog.getText(self, "Nuevo comando rápido", "Nombre:")
        if not ok or not name.strip():
            return
        command, ok = QInputDialog.getMultiLineText(self, "Nuevo comando rápido", "Comando:")
        if not ok or not command.strip():
            return
        self.config.setdefault("quick_commands", []).append({"name": name.strip()[:120], "command": command.strip()[:12000]})
        save_config(self.config)
        self.load_quick_commands()

    def edit_quick_command(self):
        idx = self._quick_command_index()
        if idx is None:
            return
        commands = self.config.get("quick_commands", [])
        if idx >= len(commands):
            return
        current = commands[idx]
        name, ok = QInputDialog.getText(self, "Editar comando rápido", "Nombre:", text=str(current.get("name", "")))
        if not ok or not name.strip():
            return
        command, ok = QInputDialog.getMultiLineText(self, "Editar comando rápido", "Comando:", str(current.get("command", "")))
        if not ok or not command.strip():
            return
        commands[idx] = {"name": name.strip()[:120], "command": command.strip()[:12000]}
        save_config(self.config)
        self.load_quick_commands()

    def delete_quick_command(self):
        idx = self._quick_command_index()
        if idx is None:
            return
        commands = self.config.get("quick_commands", [])
        if idx >= len(commands):
            return
        if QMessageBox.question(self, "Eliminar comando", f"¿Eliminar '{commands[idx].get('name','')}'?") != QMessageBox.StandardButton.Yes:
            return
        commands.pop(idx)
        save_config(self.config)
        self.load_quick_commands()

    def quick_command_context(self, pos):
        menu = QMenu(self)
        insert = menu.addAction("Insertar en Compose (sin ejecutar)")
        run = menu.addAction("Ejecutar en terminal actual")
        multi = menu.addAction("⚡ Ejecutar en MultiExec")
        menu.addSeparator()
        edit = menu.addAction("Editar")
        delete = menu.addAction("Eliminar")
        chosen = menu.exec(self.quick_command_list.viewport().mapToGlobal(pos))
        if chosen == insert:
            self.insert_selected_quick_command()
        elif chosen == run:
            self.execute_selected_quick_command()
        elif chosen == multi:
            self.execute_selected_quick_command_multiexec()
        elif chosen == edit:
            self.edit_quick_command()
        elif chosen == delete:
            self.delete_quick_command()

    def _save_platon_profile(
        self,
        name,
        username,
        password,
    ):
        """Guarda sólo la identidad estable; nunca el endpoint temporal."""
        if not credential_store_available():
            raise CredentialStoreError(
                "Windows Credential Manager no está disponible."
            )

        profile = dict(DEFAULT_SESSION)
        profile.update(
            {
                "name": str(name).strip() or f"Platon • {username}",
                "host": "PLATON",
                "port": 22,
                "username": str(username).strip(),
                "auth_mode": "platon_saved",
                "key_file": "",
                "remember_password": True,
                "credential_id": new_credential_id(),
                "remote_home": "",
                "remote_inbox": "",
            }
        )

        credential_write_password(
            profile,
            str(password)
        )

        self.config["sessions"].append(
            profile
        )
        save_config(self.config)
        self.load_sessions()

        wanted_index = len(
            self.config["sessions"]
        ) - 1

        for row in range(
            self.session_list.count()
        ):
            item = self.session_list.item(row)
            if (
                item.data(Qt.ItemDataRole.UserRole)
                == wanted_index
            ):
                self.session_list.setCurrentRow(row)
                break

        self.status.showMessage(
            "Perfil Platon guardado en Windows",
            3500
        )
        return profile

    def connect_saved_platon_profile(
        self,
        profile,
    ):
        """
        Sólo pide el código temporal; usuario y password del su
        salen del perfil + Windows Credential Manager.
        """
        profile = dict(profile or {})

        if not credential_store_available():
            QMessageBox.critical(
                self,
                "Perfil Platon",
                "Windows Credential Manager no está disponible."
            )
            return

        try:
            jump_password = credential_read_password(
                profile
            )
        except CredentialStoreError as exc:
            QMessageBox.critical(
                self,
                "Perfil Platon",
                "No se pudo leer la contraseña guardada:\n"
                + str(exc)
            )
            return

        if jump_password is None:
            QMessageBox.warning(
                self,
                "Perfil Platon",
                "Este perfil no tiene contraseña guardada. "
                "Edítalo y registra una nueva contraseña."
            )
            return

        dialog = PlatonEndpointDialog(
            profile,
            self
        )

        if (
            dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        endpoint = dialog.value()

        target_username = str(
            profile.get("username", "")
        ).strip()

        runtime = dict(DEFAULT_SESSION)
        runtime.update(
            {
                "name": str(
                    profile.get(
                        "name",
                        f"Platon • {target_username}"
                    )
                ),
                "host": endpoint["host"],
                "port": int(endpoint["port"]),
                "username": target_username,
                "auth_mode": "platon_none",
                "key_file": "",
                "remember_password": False,
                "credential_id": "",
                "remote_home": "",
                "remote_inbox": "",
                "_platon_ephemeral": True,
                "_platon_saved_runtime": True,
                "_platon_command": endpoint["command"],
                "_platon_outer_username": str(
                    endpoint["username"]
                ).strip(),
                "_platon_jump_enabled": True,
                "_platon_jump_username": target_username,
                "startup_command": str(profile.get("startup_command", "") or ""),
                "folder": str(profile.get("folder", "") or ""),
                "favorite": bool(profile.get("favorite", False)),
                "_persist_config_index": profile.get("_persist_config_index"),
                "_persist_credential_id": str(profile.get("credential_id", "") or ""),
                "_persist_identity": profile.get("_persist_identity"),
            }
        )

        self.open_connection(
            runtime,
            password=jump_password,
        )

    def new_platon_session(self):
        dialog = PlatonCommandDialog(
            self
        )

        if (
            dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        endpoint = dialog.value()

        jump_enabled = bool(
            endpoint.get(
                "jump_enabled",
                False
            )
        )

        outer_username = str(
            endpoint["username"]
        ).strip()

        jump_username = str(
            endpoint.get(
                "jump_username",
                ""
            )
        ).strip()

        # La identidad visible y efectiva es el usuario destino cuando
        # se solicita el segundo salto.
        effective_username = (
            jump_username
            if jump_enabled
            else outer_username
        )

        session = dict(
            DEFAULT_SESSION
        )

        session.update(
            {
                "name": (
                    f"Platon • "
                    f"{effective_username}@"
                    f"{endpoint['port']}"
                ),
                "host": endpoint["host"],
                "port": int(
                    endpoint["port"]
                ),
                "username": effective_username,
                "auth_mode": "platon_none",
                "key_file": "",
                "remember_password": False,
                "credential_id": "",
                "remote_home": "",
                "remote_inbox": "",
                "_platon_ephemeral": True,
                "_platon_command": endpoint["command"],
                "_platon_outer_username": outer_username,
                "_platon_jump_enabled": jump_enabled,
                "_platon_jump_username": jump_username,
            }
        )

        jump_password = (
            endpoint.get("jump_password")
            if jump_enabled
            else None
        )

        if endpoint.get("save_profile"):
            try:
                self._save_platon_profile(
                    endpoint.get("profile_name", ""),
                    jump_username,
                    jump_password,
                )
            except CredentialStoreError as exc:
                QMessageBox.warning(
                    self,
                    "Guardar perfil Platon",
                    "La conexión temporal continuará, pero el perfil "
                    "no pudo guardarse:\n" + str(exc)
                )

        # Endpoint temporal y usuario temporal nunca se persisten.
        self.open_connection(
            session,
            password=jump_password,
        )

    def open_platon_connection(
        self,
        session,
        jump_password=None,
    ):
        """
        Conecta el endpoint temporal sin persistirlo.
        La autenticación es SSH 'none'; host-key sigue siendo explícita.
        """
        session = dict(session)

        session["_ssh_keepalive"] = int(
            self.config.get(
                "ssh_keepalive",
                20
            )
        )
        session["_ssh_connect_timeout"] = int(
            self.config.get(
                "ssh_connect_timeout",
                12
            )
        )
        session["_ssh_auth_timeout"] = int(
            self.config.get(
                "ssh_auth_timeout",
                15
            )
        )
        session["_ssh_health_interval"] = int(
            self.config.get(
                "ssh_health_interval",
                5
            )
        )
        session["_auto_focus_terminal"] = bool(
            self.config.get(
                "auto_focus_terminal",
                True
            )
        )
        session["_ssh_compression"] = bool(
            self.config.get(
                "ssh_compression",
                False
            )
        )
        session["_auto_reconnect"] = False
        session["_auto_reconnect_attempts"] = 1
        session["_auto_reconnect_delay"] = 1
        session["_sftp_show_hidden_default"] = bool(
            self.config.get(
                "sftp_show_hidden_default",
                True
            )
        )
        session["_sftp_follow_terminal_folder"] = bool(
            self.config.get("sftp_follow_terminal_folder", True)
        )

        self.status.showMessage(
            f"Platon: conectando a "
            f"{session['username']}@"
            f"{session['host']}:{session['port']}..."
        )
        self.connection_status.setText(
            "⚡ Platon conectando..."
        )

        connection = PlatonConnection(
            session,
            jump_password=jump_password,
        )

        def work(progress):
            del progress
            return connection.connect(
                password=jump_password
            )

        worker = Worker(
            work
        )

        worker.signals.finished.connect(
            lambda _:
                self.connection_ready(
                    session,
                    connection,
                    password=jump_password
                )
        )

        worker.signals.error.connect(
            lambda error:
                self.connection_failed(
                    session,
                    connection,
                    error,
                    password=jump_password,
                    passphrase=None,
                    password_from_windows=False
                )
        )

        self.pool.start(
            worker
        )

    def open_local_shell(self, shell_kind="powershell"):
        """
        Abre PowerShell/CMD DENTRO del área central de MobHector.

        Backend: Windows ConPTY.
        Frontend: el mismo TerminalWidget/xterm.js de una sesión SSH.
        """
        if os.name != "nt":
            QMessageBox.information(
                self,
                "Local Shell",
                "Local Shell integrado está disponible en Windows."
            )
            return

        try:
            # Validar ConPTY antes de crear la pestaña.
            LocalConPTYChannel._api()

            tab = LocalShellTerminal(
                shell_kind,
                self.config.get(
                    "terminal_zoom",
                    100
                ),
                appearance_mode=self.config.get(
                    "appearance_mode",
                    "dark"
                ),
                terminal_theme=self.config.get(
                    "terminal_theme",
                    "follow"
                ),
                background_image=self.config.get(
                    "background_image",
                    ""
                ),
                background_blur=self.config.get(
                    "background_blur",
                    18
                ),
                glass_darkness=self.config.get(
                    "glass_darkness",
                    68
                ),
                clipboard_preferences=(
                    self.terminal_clipboard_preferences()
                ),
                terminal_preferences=(
                    self.terminal_runtime_preferences()
                ),
            )

        except Exception as exc:
            LOGGER.exception(
                "No se pudo crear Local Shell integrado"
            )
            QMessageBox.critical(
                self,
                "Local Shell integrado",
                "No se pudo abrir el pseudo-terminal local de Windows.\\n\\n"
                + compact_error(exc)
                + "\\n\\nSe requiere Windows 10 1809 o posterior."
            )
            return

        tab.status_message.connect(
            self.status.showMessage
        )
        tab.terminal.zoom_changed.connect(
            self.terminal_zoom_changed
        )
        tab.terminal.user_input.connect(
            lambda data, source=tab:
                self.handle_multi_exec_input(source, data)
        )
        tab.terminal.paste_input.connect(
            lambda data, source=tab:
                self.handle_multi_exec_paste(source, data)
        )
        tab.close_requested.connect(
            lambda source=tab:
                self.close_local_shell_widget(source)
        )

        idx = self.tabs.addTab(
            tab,
            f">_ {tab.display_name}"
        )
        self.tabs.setCurrentIndex(idx)

        self.side_stack.setCurrentWidget(
            self.sftp_placeholder
        )
        self.sftp_dock.setWindowTitle(
            "SFTP / Archivos — no disponible en Local Shell"
        )

        self.connection_status.setText(
            f">_ LOCAL • {tab.display_name}"
        )

        self.status.showMessage(
            f"{tab.display_name} abierto dentro de MobHector",
            3500
        )

        QTimer.singleShot(
            120,
            tab.terminal.fit_terminal
        )
        QTimer.singleShot(
            220,
            tab.terminal.focus_terminal
        )
        QTimer.singleShot(
            0,
            self.backdrop.refresh_after_session_open
        )

    def close_local_shell_widget(self, tab):
        if not isinstance(
            tab,
            LocalShellTerminal
        ):
            return

        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.close_tab(idx)

    def build_sftp_dock(self):
        self.sftp_dock = QDockWidget("Archivos", self)
        self.sftp_dock.setObjectName("SftpDock")

        # Permitir colocarlo donde el usuario quiera.
        self.sftp_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea |
            Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.sftp_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.sftp_dock.setMinimumWidth(360)

        self.side_stack = QStackedWidget()
        self.side_stack.setObjectName("SftpStack")

        self.sftp_placeholder = QLabel(
            "Conecta una sesión SSH\n"
            "para mostrar SFTP / Windows."
        )
        self.sftp_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.sftp_placeholder.setObjectName("muted")
        self.side_stack.addWidget(self.sftp_placeholder)

        self.sftp_dock.setWidget(self.side_stack)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea,
            self.sftp_dock
        )

        # Disposición cómoda por defecto:
        # Sesiones y SFTP comparten la misma franja izquierda y el usuario
        # cambia entre ellos mediante pestañas. Se pueden separar arrastrando.
        self.tabifyDockWidget(self.sessions_dock, self.sftp_dock)
        self.sessions_dock.raise_()

    def build_transfer_dock(self):
        self.transfers = TransferDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.transfers)
        self.transfers.hide()

    def toolbar_item_definitions(self):
        return [
            {"id": "new", "label": "+ Sesión"},
            {"id": "quick_connect", "label": "Quick Connect"},
            {"id": "local", "label": "Local"},
            {"id": "connect", "label": "Conectar"},
            {"id": "compose", "label": "Compose"},
            {"id": "reconnect", "label": "Reconectar"},
            {"id": "refresh", "label": "Actualizar"},
            {"id": "sessions", "label": "Sesiones"},
            {"id": "sftp", "label": "Archivos"},
            {"id": "transfers", "label": "Transferencias"},
            {"id": "multiexec", "label": "MultiExec"},
            {"id": "search", "label": "Buscar"},
            {"id": "recorder", "label": "Recorder"},
            {"id": "startup", "label": "Startup"},
            {"id": "appearance", "label": "Apariencia"},
            {"id": "zoom", "label": "Zoom"},
            {"id": "zen", "label": "Zen"},
            {"id": "fullscreen", "label": "Pantalla completa"},
        ]

    def _toolbar_default_layout(self):
        return [meta["id"] for meta in self.toolbar_item_definitions()]

    def _normalize_toolbar_config(self):
        defaults = self._toolbar_default_layout()
        layout = [str(x) for x in self.config.get("toolbar_layout", defaults)]
        hidden = [str(x) for x in self.config.get("toolbar_hidden", [])]
        known = set(defaults)
        clean_layout = []
        seen = set()
        for item_id in layout + defaults:
            if item_id in known and item_id not in seen:
                clean_layout.append(item_id)
                seen.add(item_id)
        clean_hidden = [item_id for item_id in hidden if item_id in known]
        self.config["toolbar_layout"] = clean_layout
        self.config["toolbar_hidden"] = clean_hidden

    def build_toolbar(self):
        tb = QToolBar("Principal", self)
        tb.setObjectName("MainToolbar")
        tb.setMovable(True)
        tb.setFloatable(True)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tb.customContextMenuRequested.connect(self.show_toolbar_context_menu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.main_toolbar = tb
        self._normalize_toolbar_config()
        self.rebuild_toolbar(save=False)

    def _build_toolbar_local_widget(self):
        button = QToolButton()
        button.setText(">_ Local")
        button.setToolTip("Abrir shells locales dentro de MobHector")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.clicked.connect(lambda: self.open_local_shell("powershell"))
        menu = QMenu(button)
        menu.addAction("PowerShell", lambda: self.open_local_shell("powershell"))
        menu.addAction("CMD", lambda: self.open_local_shell("cmd"))
        menu.addAction("WSL", lambda: self.open_local_shell("wsl"))
        menu.addAction("Git Bash", lambda: self.open_local_shell("gitbash"))
        button.setMenu(menu)
        return button

    def _build_toolbar_compose_widget(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        compose_label = QLabel("Compose:")
        compose_label.setObjectName("muted")
        lay.addWidget(compose_label)
        self.compose_edit = QLineEdit()
        self.compose_edit.setObjectName("ComposeBar")
        self.compose_edit.setPlaceholderText("Escribe un comando y Enter para la terminal actual…")
        self.compose_edit.setMinimumWidth(260)
        self.compose_edit.setMaximumWidth(620)
        self.compose_edit.returnPressed.connect(self.send_compose_current)
        lay.addWidget(self.compose_edit)
        compose_send = QPushButton("Enviar")
        compose_send.setToolTip("Enviar sólo a la terminal actual")
        compose_send.clicked.connect(self.send_compose_current)
        lay.addWidget(compose_send)
        compose_multi = QPushButton("⚡")
        compose_multi.setToolTip("Enviar una vez a cada terminal activa de MultiExec")
        compose_multi.clicked.connect(self.send_compose_multiexec)
        lay.addWidget(compose_multi)
        return box

    def _build_toolbar_zoom_widget(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        zoom_out = QToolButton()
        zoom_out.setDefaultAction(self.act_zoom_out)
        lay.addWidget(zoom_out)
        self.zoom_indicator = QLabel(f" {int(self.config.get('terminal_zoom', 100))}% ")
        self.zoom_indicator.setObjectName("zoomIndicator")
        self.zoom_indicator.setMinimumWidth(54)
        self.zoom_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.zoom_indicator)
        zoom_in = QToolButton()
        zoom_in.setDefaultAction(self.act_zoom_in)
        lay.addWidget(zoom_in)
        zoom_reset = QToolButton()
        zoom_reset.setDefaultAction(self.act_zoom_reset)
        lay.addWidget(zoom_reset)
        return box

    def rebuild_toolbar(self, save=True):
        self._normalize_toolbar_config()
        tb = self.main_toolbar
        tb.clear()
        self.compose_edit = None
        hidden = set(self.config.get("toolbar_hidden", []))
        layout = list(self.config.get("toolbar_layout", self._toolbar_default_layout()))

        action_map = {
            "new": self.act_new,
            "quick_connect": self.act_quick_connect,
            "connect": self.act_connect,
            "reconnect": self.act_reconnect,
            "refresh": self.act_refresh,
            "multiexec": self.act_multiexec,
            "search": self.act_terminal_search,
            "recorder": self.act_transcript,
            "startup": self.act_startup_command,
            "zen": self.act_zen,
            "fullscreen": self.act_fullscreen,
        }
        widget_builders = {
            "local": self._build_toolbar_local_widget,
            "compose": self._build_toolbar_compose_widget,
            "zoom": self._build_toolbar_zoom_widget,
        }
        toggle_map = {
            "sessions": self.sessions_dock.toggleViewAction(),
            "sftp": self.sftp_dock.toggleViewAction(),
            "transfers": self.transfers.toggleViewAction(),
        }
        toggle_map["sessions"].setText("Sesiones")
        toggle_map["sftp"].setText("Archivos")
        toggle_map["transfers"].setText("Transferencias")

        appearance_action = QAction("Apariencia", self)
        appearance_action.triggered.connect(self.open_appearance)

        for item_id in layout:
            if item_id in hidden:
                continue
            if item_id in action_map:
                tb.addAction(action_map[item_id])
            elif item_id in toggle_map:
                tb.addAction(toggle_map[item_id])
            elif item_id == "appearance":
                tb.addAction(appearance_action)
            elif item_id in widget_builders:
                wa = QWidgetAction(tb)
                wa.setDefaultWidget(widget_builders[item_id]())
                tb.addAction(wa)

        tb.addSeparator()
        tb.addAction(self.act_customize_toolbar)
        if self.compose_edit is None:
            self.compose_edit = QLineEdit()
            self.compose_edit.hide()
        if save:
            save_config(self.config)

    def show_toolbar_context_menu(self, pos):
        menu = QMenu(self)
        custom = menu.addAction("Personalizar barra…")
        menu.addSeparator()
        hidden = set(self.config.get("toolbar_hidden", []))
        for meta in self.toolbar_item_definitions():
            act = menu.addAction(meta["label"])
            act.setCheckable(True)
            act.setChecked(meta["id"] not in hidden)
            act.setData(meta["id"])
        chosen = menu.exec(self.main_toolbar.mapToGlobal(pos))
        if not chosen:
            return
        if chosen == custom:
            self.customize_toolbar()
            return
        item_id = chosen.data()
        if not item_id:
            return
        hidden = set(self.config.get("toolbar_hidden", []))
        if chosen.isChecked():
            hidden.discard(item_id)
        else:
            hidden.add(item_id)
        self.config["toolbar_hidden"] = list(hidden)
        self.rebuild_toolbar()

    def customize_toolbar(self):
        self._normalize_toolbar_config()
        dlg = ToolbarCustomizeDialog(
            self.toolbar_item_definitions(),
            self.config.get("toolbar_layout", self._toolbar_default_layout()),
            self.config.get("toolbar_hidden", []),
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        layout, hidden = dlg.value()
        self.config["toolbar_layout"] = layout
        self.config["toolbar_hidden"] = hidden
        self.rebuild_toolbar()

    def focus_compose_bar(self):
        if hasattr(self, "compose_edit"):
            self.compose_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.compose_edit.selectAll()

    def set_compose_text(self, text):
        value = str(text or "").strip()
        if not hasattr(self, "compose_edit"):
            return
        if "\n" in value or "\r" in value:
            edited, ok = QInputDialog.getMultiLineText(
                self,
                "Compose Buffer — no ejecutado",
                "Snippet multilínea. Edítalo/revísalo y copia lo necesario; "
                "Cancelar no ejecuta nada:",
                value,
            )
            if ok:
                QApplication.clipboard().setText(edited)
                self.compose_edit.setText("[bloque multilínea copiado al portapapeles]")
                self.compose_edit.selectAll()
            return
        self.compose_edit.setText(value)
        self.focus_compose_bar()

    def _compose_command(self):
        if not hasattr(self, "compose_edit"):
            return ""
        return str(self.compose_edit.text() or "").strip()

    def send_compose_current(self):
        command = self._compose_command()
        if not command or command.startswith("[bloque multilínea"):
            return
        if self.multi_exec_active:
            QMessageBox.information(
                self,
                "Compose Bar",
                "MultiExec está activo. Usa el botón ⚡ para enviar a las terminales "
                "activas, evitando destinos ambiguos."
            )
            return
        tab = self.current_terminal_tab()
        if not isinstance(tab, (SessionTerminal, LocalShellTerminal)):
            QMessageBox.information(self, "Compose Bar", "Abre o selecciona una terminal primero.")
            return
        if tab.terminal.send_session_command(command):
            self.status.showMessage("Compose: comando enviado a la terminal actual", 2200)
            self.compose_edit.selectAll()

    def _command_is_high_risk(self, command):
        text = str(command or "").casefold()
        risky = (
            "rm -rf", "mkfs", "lvremove", "vgremove", "pvremove",
            "shutdown", "poweroff", "reboot", "init 0", "init 6",
            "userdel", "groupdel", "wipefs", "dd if=", "> /dev/",
        )
        return any(token in text for token in risky)

    def send_command_multiexec(self, command, source_label="Compose"):
        command = str(command or "").strip()
        if not command:
            return False
        if not self.multi_exec_active or self.multi_exec_page is None:
            QMessageBox.information(
                self,
                source_label,
                "Activa MultiExec y marca las terminales destino antes de usar ⚡."
            )
            return False
        targets = list(self.multi_exec_page.enabled_tabs())
        if not targets:
            QMessageBox.information(
                self, source_label, "No hay terminales activas en MultiExec."
            )
            return False
        if self._command_is_high_risk(command) or bool(
            self.config.get("confirm_multiexec", False)
        ):
            names = "\n".join(
                "  • " + str(
                    t.session.get("name", t.session.get("host", "Terminal"))
                )
                for t in targets
            )
            answer = QMessageBox.warning(
                self,
                "Confirmar envío MultiExec",
                f"Se enviará UNA VEZ a {len(targets)} terminal(es):\n\n"
                f"{names}\n\n"
                f"Comando:\n{command}\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        delivered = 0
        for target in targets:
            try:
                # send_session_command usa announce=False: no vuelve a disparar
                # handle_multi_exec_input y evita duplicar el broadcast.
                if target.terminal.send_session_command(command, focus=False):
                    delivered += 1
            except Exception:
                LOGGER.exception(
                    "Fallo enviando comando Compose/Snippet a MultiExec"
                )
        self.status.showMessage(
            f"{source_label}: comando enviado una vez a "
            f"{delivered}/{len(targets)} terminales",
            3000,
        )
        return delivered == len(targets)

    def send_compose_multiexec(self):
        command = self._compose_command()
        if command and self.send_command_multiexec(command, source_label="Compose"):
            self.compose_edit.selectAll()

    def build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo")

        self.version_status = QLabel(f"CORE v{APP_VERSION} • {Path(__file__).name}")
        self.version_status.setObjectName("muted")
        self.status.addPermanentWidget(self.version_status)

        self.connection_status = QLabel("Sin conexión")
        self.connection_status.setObjectName("muted")
        self.status.addPermanentWidget(self.connection_status)

    def build_menus(self):
        file_m = self.menuBar().addMenu("Archivo")
        file_m.addAction(self.act_new)
        file_m.addAction(self.act_quick_connect)
        file_m.addAction(self.act_connect)
        file_m.addSeparator()
        export_a = file_m.addAction("Exportar sesiones (sin secretos)…")
        export_a.triggered.connect(self.export_sessions_safe)
        import_a = file_m.addAction("Importar sesiones…")
        import_a.triggered.connect(self.import_sessions_safe)
        file_m.addSeparator()
        quit_a = file_m.addAction("Salir")
        quit_a.triggered.connect(self.close)

        session_m = self.menuBar().addMenu("Sesión")

        local_shell_action = QAction("Local Shell integrado (PowerShell)", self)
        local_shell_action.triggered.connect(
            lambda: self.open_local_shell("powershell")
        )
        session_m.addAction(local_shell_action)
        local_wsl_action = QAction("Local Shell integrado (WSL)", self)
        local_wsl_action.triggered.connect(lambda: self.open_local_shell("wsl"))
        session_m.addAction(local_wsl_action)
        local_git_action = QAction("Local Shell integrado (Git Bash)", self)
        local_git_action.triggered.connect(lambda: self.open_local_shell("gitbash"))
        session_m.addAction(local_git_action)
        session_m.addSeparator()

        session_m.addAction(self.act_connect)
        session_m.addAction(self.act_reconnect)
        session_m.addAction(self.act_refresh)
        session_m.addAction(self.act_startup_command)
        session_m.addSeparator()
        session_m.addAction(self.act_multiexec)
        session_m.addAction(self.act_detach)
        session_m.addSeparator()
        session_m.addAction(self.act_terminal_search)
        session_m.addAction(self.act_terminal_search_next)
        session_m.addAction(self.act_terminal_search_prev)
        session_m.addAction(self.act_transcript)
        reattach_all = session_m.addAction("Reacoplar todas las ventanas")
        reattach_all.triggered.connect(self.reattach_all_detached)
        session_m.addSeparator()
        edit_a = session_m.addAction("Editar sesión")
        edit_a.triggered.connect(self.edit_session)
        del_a = session_m.addAction("Eliminar sesión")
        del_a.triggered.connect(self.delete_session)
        forget_key_a = session_m.addAction("Olvidar clave SSH del servidor")
        forget_key_a.triggered.connect(self.forget_selected_host_key)

        view_m = self.menuBar().addMenu("Ver")
        sessions_a = self.sessions_dock.toggleViewAction()
        sessions_a.setShortcut(QKeySequence("Ctrl+Shift+E"))

        files_a = self.sftp_dock.toggleViewAction()
        files_a.setText("SFTP / Archivos")
        files_a.setShortcut(QKeySequence("Ctrl+Shift+S"))

        transfers_a = self.transfers.toggleViewAction()
        transfers_a.setShortcut(QKeySequence("Ctrl+Shift+J"))

        quick_a = self.quick_commands_dock.toggleViewAction()
        quick_a.setText("Snippets / Macros")
        quick_a.setShortcut(QKeySequence("Ctrl+Shift+B"))

        view_m.addAction(sessions_a)
        view_m.addAction(files_a)
        view_m.addAction(transfers_a)
        view_m.addAction(quick_a)

        restore_panels = QAction("Restablecer paneles", self)
        restore_panels.setShortcut(QKeySequence("Ctrl+Shift+R"))
        restore_panels.triggered.connect(self.reset_panel_layout)
        view_m.addAction(restore_panels)
        view_m.addAction(self.act_customize_toolbar)
        view_m.addSeparator()
        view_m.addAction(self.act_zoom_in)
        view_m.addAction(self.act_zoom_out)
        view_m.addAction(self.act_zoom_reset)
        view_m.addSeparator()
        view_m.addAction(self.act_zen)
        view_m.addAction(self.act_fullscreen)
        view_m.addSeparator()

        appearance_a = QAction("Apariencia…", self)
        appearance_a.triggered.connect(self.open_appearance)
        view_m.addAction(appearance_a)

        settings_m = self.menuBar().addMenu("Configuración")

        general_settings_a = QAction(
            "Preferencias generales…",
            self
        )
        general_settings_a.triggered.connect(
            self.open_general_settings
        )
        settings_m.addAction(general_settings_a)

        terminal_settings_a = QAction(
            "Terminal / Teclado / Portapapeles…",
            self
        )
        terminal_settings_a.triggered.connect(
            self.open_terminal_settings
        )
        settings_m.addAction(terminal_settings_a)

        appearance_settings_a = QAction("Apariencia…", self)
        appearance_settings_a.triggered.connect(self.open_appearance)
        settings_m.addAction(appearance_settings_a)

        settings_m.addSeparator()

        config_folder_a = QAction(
            "Abrir carpeta de configuración",
            self
        )
        config_folder_a.triggered.connect(
            self.open_config_folder
        )
        settings_m.addAction(config_folder_a)

        log_folder_a = QAction(
            "Abrir carpeta de logs",
            self
        )
        log_folder_a.triggered.connect(
            self.open_log_folder
        )
        settings_m.addAction(log_folder_a)

        credentials_a = QAction(
            "Abrir credenciales de Windows…",
            self
        )
        credentials_a.triggered.connect(
            self.open_windows_credentials
        )
        settings_m.addAction(credentials_a)

        settings_m.addSeparator()

        reset_settings_a = QAction(
            "Restablecer preferencias…",
            self
        )
        reset_settings_a.triggered.connect(
            self.reset_preferences
        )
        settings_m.addAction(reset_settings_a)

        help_m = self.menuBar().addMenu("Ayuda")
        shortcuts = help_m.addAction("Atajos")
        shortcuts.triggered.connect(self.show_shortcuts)
        about = help_m.addAction("Acerca de")
        about.triggered.connect(self.about)

    # ---------------- sessions list ----------------

    def load_sessions(self):
        self.session_list.clear()

        for idx, s in enumerate(
            self.config["sessions"]
        ):
            auth_mode = s.get("auth_mode")

            if auth_mode == "platon_saved":
                saved = (
                    bool(s.get("remember_password"))
                    and credential_has_password(s)
                )

                auth_label = (
                    "⚡ Platon guardado • ✓ Windows"
                    if saved
                    else "⚡ Platon guardado • sin contraseña"
                )

                item = QListWidgetItem(
                    f"⚡  {s.get('name', 'Platon')}\n"
                    f"    su - {s.get('username','')}  •  {auth_label}"
                )
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    idx
                )
                item.setToolTip(
                    "Perfil Platon guardado\n"
                    f"Usuario destino: {s.get('username','')}\n"
                    "Al conectar sólo se solicita el comando ssh.exe "
                    "temporal de Platon.\n"
                    + (
                        "Contraseña protegida por Windows Credential Manager"
                        if saved
                        else "Falta contraseña protegida"
                    )
                )
                self.session_list.addItem(item)
                continue

            if auth_mode not in ("key", "password"):
                auth_mode = (
                    "key"
                    if s.get("key_file")
                    else "password"
                )
                s["auth_mode"] = auth_mode

            if auth_mode == "key":
                auth_label = "🔑 Llave SSH"
                credential_note = ""
            else:
                saved = (
                    bool(s.get("remember_password"))
                    and credential_has_password(s)
                )
                auth_label = (
                    "🔐 Contraseña • ✓ Windows"
                    if saved
                    else "🔐 Contraseña • Pedir"
                )
                credential_note = (
                    "\nContraseña protegida por Windows Credential Manager"
                    if saved
                    else ""
                )

            favorite = "⭐" if bool(s.get("favorite", False)) else "●"
            folder = str(s.get("folder", "")).strip()
            folder_note = f"  •  📁 {folder}" if folder else ""
            item = QListWidgetItem(
                f"{favorite}  {s.get('name', s.get('host',''))}\n"
                f"    {s.get('username','')}@{s.get('host','')}  •  {auth_label}{folder_note}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                idx
            )
            item.setToolTip(
                f"{s.get('username','')}@{s.get('host','')}:"
                f"{s.get('port',22)}\n"
                f"Autenticación: {auth_label}{credential_note}"
            )
            self.session_list.addItem(item)

        if self.session_list.count():
            self.session_list.setCurrentRow(0)

    def filter_sessions(self, text):
        term = text.casefold().strip()
        for i in range(self.session_list.count()):
            item = self.session_list.item(i)
            item.setHidden(term not in item.text().casefold())

    def session_index(self):
        item = self.session_list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def selected_session(self):
        idx = self.session_index()
        if idx is None:
            return None
        return self.config["sessions"][idx]

    def new_session(self):
        dlg = SessionDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            s = dlg.value()
            if not s["host"] or not s["username"]:
                QMessageBox.warning(self, "Sesión", "Host y usuario son obligatorios.")
                return
            self.config["sessions"].append(s)
            save_config(self.config)
            self.load_sessions()
            self.session_list.setCurrentRow(len(self.config["sessions"]) - 1)

    def edit_session(self):
        idx = self.session_index()

        if idx is None:
            return

        current = dict(
            self.config["sessions"][idx]
        )

        if current.get("auth_mode") == "platon_saved":
            dlg = SavedPlatonProfileDialog(
                current,
                self
            )

            if (
                dlg.exec()
                != QDialog.DialogCode.Accepted
            ):
                return

            value = dlg.value()

            old_username = str(
                current.get("username", "")
            )
            new_username = str(
                value.get("username", "")
            )
            new_password = str(
                value.get("new_password", "")
            )

            if (
                old_username != new_username
                and not new_password
            ):
                QMessageBox.warning(
                    self,
                    "Perfil Platon",
                    "Al cambiar el usuario del su -, escribe también "
                    "la nueva contraseña."
                )
                return

            current["name"] = value["name"]
            current["username"] = new_username
            current["host"] = "PLATON"
            current["port"] = 22
            current["auth_mode"] = "platon_saved"
            current["remember_password"] = True

            if not current.get("credential_id"):
                current["credential_id"] = new_credential_id()

            if new_password:
                try:
                    credential_write_password(
                        current,
                        new_password
                    )
                except CredentialStoreError as exc:
                    QMessageBox.critical(
                        self,
                        "Perfil Platon",
                        "No se pudo guardar la contraseña:\n"
                        + str(exc)
                    )
                    return

            self.config["sessions"][idx] = current
            save_config(self.config)
            self.load_sessions()
            self.session_list.setCurrentRow(idx)
            self.status.showMessage(
                "Perfil Platon actualizado",
                3000
            )
            return

        dlg = SessionDialog(
            self,
            current
        )
        if (
            dlg.exec()
            == QDialog.DialogCode.Accepted
        ):
            self.config["sessions"][idx] = dlg.value()
            save_config(self.config)
            self.load_sessions()
            self.session_list.setCurrentRow(idx)

    def forget_selected_host_key(self):
        session = self.selected_session()

        if not session:
            return

        if session.get("auth_mode") == "platon_saved":
            QMessageBox.information(
                self,
                "Perfil Platon",
                "Este perfil no tiene host/puerto fijo. "
                "La clave SSH se valida contra el endpoint temporal "
                "cuando conectas."
            )
            return

        host = session.get("host", "")
        port = int(session.get("port", 22))
        candidates = [host]
        if port != 22:
            candidates.insert(0, f"[{host}]:{port}")

        if QMessageBox.question(
            self,
            "Olvidar clave SSH",
            f"¿Eliminar la clave de host guardada para {host}:{port}?\n\n"
            "En la próxima conexión MobHector volverá a mostrar la huella "
            "para que puedas verificarla."
        ) != QMessageBox.StandardButton.Yes:
            return

        removed = False
        for candidate in candidates:
            try:
                removed = remove_trusted_host(
                    KNOWN_HOSTS_FILE,
                    candidate
                ) or removed
            except Exception:
                LOGGER.exception("No se pudo eliminar host key %s", candidate)

        self.status.showMessage(
            "Clave SSH eliminada" if removed else "No había una clave MobHector guardada",
            3500,
        )

    def delete_session(self):
        idx = self.session_index()
        if idx is None:
            return

        s = self.config["sessions"][idx]

        if (
            QMessageBox.question(
                self,
                "Eliminar",
                f"¿Eliminar '{s.get('name')}'?\n\n"
                "Si tiene una contraseña guardada en Windows, "
                "también será eliminada."
            )
            == QMessageBox.StandardButton.Yes
        ):
            try:
                if (
                    s.get("auth_mode")
                    in ("password", "platon_saved")
                    and s.get("credential_id")
                ):
                    credential_delete_password(s)
            except CredentialStoreError as exc:
                LOGGER.warning(
                    "No se pudo borrar credencial de sesión eliminada: %s",
                    exc
                )

            self.config["sessions"].pop(idx)

            # Cero sesiones es un estado válido.
            save_config(self.config)
            self.load_sessions()

    def session_context(self, pos):
        menu = QMenu(self)
        connect = menu.addAction("Conectar")
        edit = menu.addAction("Editar")
        duplicate = menu.addAction("Duplicar")
        favorite = menu.addAction("⭐ Alternar favorito")
        menu.addSeparator()
        delete = menu.addAction("Eliminar")
        chosen = menu.exec(self.session_list.viewport().mapToGlobal(pos))
        if chosen == connect:
            self.connect_selected()
        elif chosen == edit:
            self.edit_session()
        elif chosen == duplicate:
            idx = self.session_index()

            if idx is not None:
                s = dict(
                    self.config["sessions"][idx]
                )

                if s.get("auth_mode") == "platon_saved":
                    QMessageBox.information(
                        self,
                        "Duplicar perfil Platon",
                        "Por seguridad no se duplica la contraseña guardada. "
                        "Crea el nuevo perfil desde ⚡ Platon."
                    )
                    return

                s["name"] = (
                    s.get("name", "Sesión")
                    + " copia"
                )

                # Nunca compartir el secreto de la sesión original.
                s["credential_id"] = new_credential_id()
                s["remember_password"] = False
                s.pop("password", None)
                s.pop("ssh_password", None)

                self.config["sessions"].append(s)
                save_config(self.config)
                self.load_sessions()
        elif chosen == favorite:
            idx = self.session_index()
            if idx is not None:
                self.config["sessions"][idx]["favorite"] = not bool(self.config["sessions"][idx].get("favorite", False))
                save_config(self.config)
                self.load_sessions()
        elif chosen == delete:
            self.delete_session()

    # ---------------- productividad ----------------

    def quick_connect(self):
        dlg = QuickConnectDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.open_connection(dlg.value())

    def search_current_terminal(self):
        tab = self.current_terminal_tab()
        if not isinstance(tab, (SessionTerminal, LocalShellTerminal)):
            QMessageBox.information(self, "Buscar", "Selecciona una terminal.")
            return
        value, ok = QInputDialog.getText(
            self,
            "Buscar en terminal",
            "Texto a buscar en el scrollback:",
            text=self._terminal_search_query,
        )
        if not ok or not value:
            return
        self._terminal_search_query = value
        tab.terminal.search_text(
            value,
            backwards=False,
            case_sensitive=bool(self.config.get("terminal_search_case_sensitive", False)),
        )

    def search_current_terminal_next(self, backwards=False):
        if not self._terminal_search_query:
            self.search_current_terminal()
            return
        tab = self.current_terminal_tab()
        if isinstance(tab, (SessionTerminal, LocalShellTerminal)):
            tab.terminal.search_text(
                self._terminal_search_query,
                backwards=backwards,
                case_sensitive=bool(self.config.get("terminal_search_case_sensitive", False)),
            )

    def edit_current_startup_command(self):
        tab = self.current_session_tab()
        if not isinstance(tab, SessionTerminal):
            QMessageBox.information(
                self,
                "Startup Command",
                "Selecciona una sesión SSH activa. También puedes usar el "
                "botón Inicio de la cabecera de la terminal."
            )
            return
        tab.edit_startup_command()

    def toggle_current_transcript(self):
        tab = self.current_terminal_tab()
        if not isinstance(tab, (SessionTerminal, LocalShellTerminal)):
            QMessageBox.information(self, "Transcript", "Selecciona una terminal.")
            return
        terminal = tab.terminal
        if terminal.transcript_active():
            path = terminal.stop_transcript()
            self.act_transcript.setText("● Recorder")
            self.status.showMessage(f"Transcript guardado: {path}", 5000)
        else:
            label = (
                tab.session.get("name")
                if isinstance(tab, SessionTerminal)
                else tab.display_name
            )
            try:
                path = terminal.start_transcript(label)
            except Exception as exc:
                QMessageBox.critical(self, "Transcript", compact_error(exc))
                return
            self.act_transcript.setText("■ Stop Recorder")
            self.status.showMessage(f"Grabando transcript: {path}", 5000)

    @staticmethod
    def _portable_session(session):
        allowed = {
            "name", "host", "port", "username", "auth_mode", "key_file",
            "remote_home", "remote_inbox", "folder", "startup_command", "favorite"
        }
        result = {k: session.get(k) for k in allowed if k in session}
        result["remember_password"] = False
        result.pop("credential_id", None)
        result.pop("startup_command", None)
        if result.get("auth_mode") == "platon_saved":
            return None
        return result

    def export_sessions_safe(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar sesiones sin secretos",
            str(Path.home() / "mobhector_sessions.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        sessions = []
        skipped = 0
        for session in self.config.get("sessions", []):
            portable = self._portable_session(session)
            if portable is None:
                skipped += 1
                continue
            sessions.append(portable)
        payload = {
            "format": "MobHectorPortableSessions",
            "version": 1,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": sessions,
        }
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Exportar sesiones", compact_error(exc))
            return
        msg = f"Exportadas {len(sessions)} sesiones sin contraseñas ni credential_id."
        if skipped:
            msg += f"\n\nSe omitieron {skipped} perfiles Platon porque dependen de Windows Credential Manager."
        QMessageBox.information(self, "Exportar sesiones", msg)

    def import_sessions_safe(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar sesiones",
            str(Path.home()),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            imported, skipped = read_sessions(path, self.config.get("sessions", []))
            added = len(imported)
            updated = dict(self.config)
            updated["sessions"] = self.config.get("sessions", []) + imported
            save_config(updated)
            self.config = updated
            self.load_sessions()
        except Exception as exc:
            QMessageBox.critical(self, "Importar sesiones", compact_error(exc))
            return
        QMessageBox.information(
            self,
            "Importar sesiones",
            f"Importadas {added} sesiones; {skipped} duplicadas omitidas.\nContraseñas y comandos de inicio no se importan. Configúralos después de revisar las sesiones.",
        )

    # ---------------- connection ----------------

    def connect_selected(self):
        s = self.selected_session()

        if not s:
            QMessageBox.information(
                self,
                "Sesión",
                "Selecciona una sesión."
            )
            return

        persist_identity = [
            str(s.get("name", "")),
            str(s.get("host", "")),
            int(s.get("port", 22) or 22),
            str(s.get("username", "")),
            str(s.get("auth_mode", "")),
            str(s.get("key_file", "")),
        ]

        if s.get("auth_mode") == "platon_saved":
            profile = dict(s)
            profile["_persist_config_index"] = self.session_index()
            profile["_persist_identity"] = persist_identity
            self.connect_saved_platon_profile(profile)
            return

        runtime = dict(s)
        runtime["_persist_config_index"] = self.session_index()
        runtime["_persist_identity"] = persist_identity
        self.open_connection(runtime)

    def _prompt_password(self, session, title="Contraseña SSH"):
        if session.get("remember_password"):
            note = (
                "Si autentica correctamente, se guardará protegida por "
                "Windows para próximas conexiones."
            )
        else:
            note = (
                "Se conservará sólo en memoria mientras la pestaña "
                "SSH esté abierta."
            )

        pwd, ok = QInputDialog.getText(
            self,
            title,
            f"Contraseña para {session['username']}@{session['host']}:\n"
            f"{note}",
            QLineEdit.EchoMode.Password
        )

        if not ok:
            return None
        return pwd

    def _prompt_key_passphrase(self, session):
        value, ok = QInputDialog.getText(
            self,
            "Passphrase de llave SSH",
            f"Passphrase para la llave de {session['username']}@{session['host']}:\n"
            "(no se guarda en disco)",
            QLineEdit.EchoMode.Password
        )
        if not ok:
            return None
        return value

    def open_connection(self, session, password=None, passphrase=None):
        session = dict(session)
        auth_mode = session.get("auth_mode")

        if auth_mode == "platon_none":
            self.open_platon_connection(
                session,
                jump_password=password,
            )
            return

        if auth_mode not in ("key", "password"):
            auth_mode = (
                "key"
                if session.get("key_file")
                else "password"
            )
            session["auth_mode"] = auth_mode

        password_from_windows = False

        if auth_mode == "password" and password is None:
            if (
                session.get("remember_password")
                and session.get("credential_id")
                and credential_store_available()
            ):
                try:
                    password = credential_read_password(
                        session
                    )
                    password_from_windows = (
                        password is not None
                    )

                    if password_from_windows:
                        self.status.showMessage(
                            "Usando contraseña protegida por Windows..."
                        )
                except CredentialStoreError as exc:
                    LOGGER.warning(
                        "No se pudo leer la credencial guardada: %s",
                        exc
                    )
                    password = None

            if password is None:
                password = self._prompt_password(session)

                if password is None:
                    self.status.showMessage(
                        "Conexión cancelada"
                    )
                    return

        session["_ssh_keepalive"] = int(
            self.config.get("ssh_keepalive", 20)
        )
        session["_ssh_connect_timeout"] = int(
            self.config.get("ssh_connect_timeout", 12)
        )
        session["_ssh_auth_timeout"] = int(
            self.config.get("ssh_auth_timeout", 15)
        )
        session["_ssh_health_interval"] = int(
            self.config.get("ssh_health_interval", 5)
        )
        session["_auto_focus_terminal"] = bool(
            self.config.get("auto_focus_terminal", True)
        )
        session["_ssh_compression"] = bool(
            self.config.get("ssh_compression", False)
        )
        session["_auto_reconnect"] = bool(
            self.config.get("auto_reconnect", False)
        )
        session["_auto_reconnect_attempts"] = int(
            self.config.get("auto_reconnect_attempts", 3)
        )
        session["_auto_reconnect_delay"] = int(
            self.config.get("auto_reconnect_delay", 3)
        )
        session["_sftp_show_hidden_default"] = bool(
            self.config.get("sftp_show_hidden_default", True)
        )
        session["_sftp_follow_terminal_folder"] = bool(
            self.config.get("sftp_follow_terminal_folder", True)
        )

        self.status.showMessage(
            f"Conectando a {session['username']}@{session['host']}..."
        )
        self.connection_status.setText("Conectando...")
        connection = SSHConnection(session)

        def work(progress):
            return connection.connect(password=password, passphrase=passphrase)

        w = Worker(work)
        w.signals.finished.connect(
            lambda _:
                self.connection_ready(
                    session,
                    connection,
                    password=password
                )
        )
        w.signals.error.connect(
            lambda e:
                self.connection_failed(
                    session,
                    connection,
                    e,
                    password=password,
                    passphrase=passphrase,
                    password_from_windows=password_from_windows
                )
        )
        self.pool.start(w)

    def connection_failed(
        self,
        session,
        connection,
        error,
        password=None,
        passphrase=None,
        password_from_windows=False
    ):
        summary = compact_error(error)
        connection.close(clear_secret=True)
        self.connection_status.setText("Error")
        lower = str(error).casefold()

        unknown_key = parse_unknown_marker(error)
        if unknown_key:
            fingerprint = unknown_key["fingerprint"]
            host_display = unknown_key["hostname"]
            answer = QMessageBox.warning(
                self,
                "Verificación de identidad SSH",
                "El servidor no tiene una clave de host conocida por MobHector.\n\n"
                f"Servidor: {host_display}\n"
                f"Algoritmo: {unknown_key['key_type']}\n"
                f"Huella: {fingerprint}\n\n"
                "Confía sólo si esta huella coincide con la informada por "
                "el administrador del servidor. Aceptarla sin verificar "
                "puede exponer la sesión a un ataque de intermediario.\n\n"
                "¿Confiar en esta clave y continuar?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    trust_host_key(
                        KNOWN_HOSTS_FILE,
                        unknown_key["hostname"],
                        unknown_key["key_type"],
                        unknown_key["key_base64"],
                    )
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "Clave SSH",
                        "No se pudo guardar la clave de host.\n\n"
                        + compact_error(exc)
                    )
                    return
                self.open_connection(
                    session,
                    password=password,
                    passphrase=passphrase,
                )
            return

        mismatch = parse_mismatch_marker(error)
        if mismatch:
            QMessageBox.critical(
                self,
                "ALERTA: clave SSH del servidor cambió",
                "La clave de host recibida NO coincide con la que estaba "
                "guardada. MobHector bloqueó la conexión.\n\n"
                f"Servidor: {mismatch['hostname']}\n"
                f"Esperada: {mismatch['expected_fingerprint']} "
                f"({mismatch['expected_type']})\n"
                f"Recibida: {mismatch['got_fingerprint']} "
                f"({mismatch['got_type']})\n\n"
                "Esto puede ocurrir tras una reinstalación legítima del "
                "servidor, pero también puede indicar suplantación/MITM. "
                "Verifica la nueva huella con el administrador antes de "
                "usar 'Olvidar clave SSH del servidor'."
            )
            return

        # Llave cifrada: Paramiko requiere passphrase específica.
        if (
            session.get("auth_mode", "key") == "key"
            and (
                "passwordrequiredexception" in lower
                or "private key file is encrypted" in lower
                or "private key is encrypted" in lower
            )
        ):
            phrase = self._prompt_key_passphrase(session)
            if phrase is not None:
                self.open_connection(session, password=password, passphrase=phrase)
            return

        # Contraseña incorrecta: si venía de Windows, eliminarla para no
        # quedar atrapados reintentando un secreto inválido.
        if session.get("auth_mode") == "password" and (
            "authentication" in lower or "auth" in lower
        ):
            if (
                session.get("remember_password")
                and session.get("credential_id")
            ):
                try:
                    credential_delete_password(
                        session
                    )
                except CredentialStoreError as exc:
                    LOGGER.warning(
                        "No se pudo eliminar credencial rechazada: %s",
                        exc
                    )

            answer = QMessageBox.question(
                self,
                "Autenticación SSH",
                f"No fue posible autenticar a {session['username']}@{session['host']}.\n\n"
                f"{summary}\n\n¿Deseas volver a escribir la contraseña?"
            )
            if answer == QMessageBox.StandardButton.Yes:
                retry_pwd = self._prompt_password(
                    session, "Reintentar contraseña SSH"
                )
                if retry_pwd is not None:
                    self.open_connection(session, password=retry_pwd)
            return

        QMessageBox.critical(
            self,
            "Conexión SSH",
            f"No se pudo abrir la sesión.\n\n{summary}\n\n"
            "Revisa conectividad, puerto y método de autenticación."
        )

    def connection_ready(self, session, connection, password=None):
        # Copiar sólo valores runtime resueltos desde SSHConnection.
        # `session` aquí ya es una copia y NO es la entrada persistida
        # en config.json.
        session["_resolved_remote_home"] = connection.session.get(
            "_resolved_remote_home",
            connection.session.get("remote_home", "")
        )
        session["_resolved_remote_inbox"] = connection.session.get(
            "_resolved_remote_inbox",
            connection.session.get("remote_inbox", "")
        )

        if session.get("auth_mode") == "platon_none":
            session["_platon_su_sftp_active"] = bool(
                getattr(connection, "su_sftp_active", False)
            )
            session["_platon_su_sftp_error"] = str(
                getattr(connection, "su_sftp_error", "") or ""
            )

            # El HOME SFTP efectivo es exclusivamente el que devuelve
            # la sesión SFTP Platon mediante normalize(".").
            session["_resolved_remote_home"] = (
                connection.session.get(
                    "_resolved_remote_home",
                    session.get(
                        "_resolved_remote_home",
                        ""
                    )
                )
            )

        # Guardar sólo después de una autenticación exitosa. Esto también
        # reemplaza una credencial vieja si el usuario corrigió la contraseña.
        if (
            session.get("auth_mode") == "password"
            and session.get("remember_password")
            and session.get("credential_id")
            and password is not None
            and credential_store_available()
        ):
            try:
                credential_write_password(
                    session,
                    password
                )
            except CredentialStoreError as exc:
                LOGGER.warning(
                    "Conectado, pero no se pudo guardar contraseña: %s",
                    exc
                )
                self.status.showMessage(
                    "Conectado; Windows no pudo guardar la contraseña",
                    5000
                )

        local_path = self.config.get("last_local_path", safe_local_start())
        if not os.path.isdir(local_path):
            local_path = safe_local_start()

        tab = SessionTerminal(
            session,
            connection,
            self.pool,
            self.transfers,
            local_path,
            self.config.get("terminal_zoom", 100),
            files_visible=self.config.get("workspace_files_visible", True),
            files_width=self.config.get("workspace_files_width", 455),
            appearance_mode=self.config.get("appearance_mode", "dark"),
            terminal_theme=self.config.get("terminal_theme", "follow"),
            background_image=self.config.get("background_image", ""),
            background_blur=self.config.get("background_blur", 18),
            glass_darkness=self.config.get("glass_darkness", 68),
            clipboard_preferences=self.terminal_clipboard_preferences(),
            terminal_preferences=self.terminal_runtime_preferences(),
        )
        tab.editor_requested.connect(self.open_editor)
        tab.status_message.connect(self.status.showMessage)
        tab.terminal.zoom_changed.connect(self.terminal_zoom_changed)
        tab.terminal.user_input.connect(
            lambda data, source=tab: self.handle_multi_exec_input(source, data)
        )
        tab.terminal.paste_input.connect(
            lambda data, source=tab: self.handle_multi_exec_paste(
                source, data
            )
        )
        tab.files_toggle_requested.connect(self.toggle_current_files)
        tab.startup_command_changed.connect(
            lambda value, source=tab: self.persist_startup_command_for_tab(
                source, value
            )
        )
        tab.reconnect_requested.connect(
            lambda source=tab: self.reconnect_session_tab(source)
        )
        tab.close_requested.connect(
            lambda source=tab: self.close_session_widget(source)
        )

        side_index = self.side_stack.addWidget(tab.side_panel)
        tab.side_stack_index = side_index

        tab_prefix = (
            "⚡"
            if session.get("auth_mode") == "platon_none"
            else "●"
        )

        idx = self.tabs.addTab(
            tab,
            f"{tab_prefix} {session.get('name', session['host'])}"
        )
        self.tabs.setCurrentIndex(idx)
        self.last_session_tab = tab

        self.side_stack.setCurrentWidget(tab.side_panel)
        self.sftp_dock.setWindowTitle(
            f"SFTP / Archivos — {session.get('name', session['host'])}"
        )

        if self.config.get("sftp_auto_show_on_connect", True):
            self.sftp_dock.show()
            self.config["workspace_files_visible"] = True
        else:
            self.sftp_dock.hide()
            self.config["workspace_files_visible"] = False

        self.connection_status.setText(
            (
                f"⚡ PLATON • "
                f"{session['username']}@"
                f"{session['host']}:{session.get('port', 22)}"
                if session.get("auth_mode") == "platon_none"
                else f"● {session['username']}@{session['host']}"
            )
        )
        self.status.showMessage(
            (
                (
                    "Platon: terminal con su; SFTP Platon en HOME por defecto"
                    if session.get("_platon_jump_enabled")
                    else "Platon: Terminal + SFTP listos"
                )
                if session.get("auth_mode") == "platon_none"
                else "Conectado"
            )
        )
        QTimer.singleShot(0, self.backdrop.refresh_after_session_open)

    def reconnect_current(self):
        tab = self.current_terminal_tab()

        if isinstance(tab, LocalShellTerminal):
            tab.restart_shell()
            self.status.showMessage(
                f"{tab.display_name}: terminal local reiniciada",
                2500
            )
            return

        if isinstance(tab, SessionTerminal):
            self.reconnect_session_tab(tab)

    def reconnect_session_tab(
        self,
        tab,
        password=None,
        passphrase=None
    ):
        if not isinstance(tab, SessionTerminal):
            return
        if tab._connection_state == "reconnecting":
            return
        if tab not in self.all_session_tabs():
            return

        tab.begin_reconnect()
        self.connection_status.setText("Reconectando...")
        self.status.showMessage(
            f"Reconectando {tab.session['username']}@{tab.session['host']}..."
        )
        connection = tab.connection

        def work(progress):
            # Reutiliza credenciales RAM. Si QA detectó credencial inválida,
            # password/passphrase permite reemplazarla explícitamente.
            return connection.connect(
                password=password,
                passphrase=passphrase,
            )

        w = Worker(work)
        w.signals.finished.connect(
            lambda _, source=tab, pwd=password:
                self._reconnect_ready(source, password=pwd)
        )
        w.signals.error.connect(
            lambda e, source=tab:
                self._reconnect_failed(source, e)
        )
        self.pool.start(w)

    def _reconnect_ready(self, tab, password=None):
        if tab not in self.all_session_tabs():
            try:
                tab.connection.close(clear_secret=True)
            except Exception:
                pass
            return

        if (
            password is not None
            and tab.session.get("auth_mode") == "password"
            and tab.session.get("remember_password")
            and credential_store_available()
        ):
            try:
                credential_write_password(
                    tab.session,
                    password
                )
            except CredentialStoreError as exc:
                LOGGER.warning(
                    "Reconectado pero no se pudo actualizar credencial: %s",
                    exc
                )

        tab.reconnect_success()
        self.connection_status.setText(
            f"● {tab.session['username']}@{tab.session['host']}"
        )
        self.status.showMessage("Conexión SSH restablecida", 3000)

    def _reconnect_failed(self, tab, error):
        if tab not in self.all_session_tabs():
            return

        tab.reconnect_failed(error)
        self.connection_status.setText("SSH desconectado")

        unknown_key = parse_unknown_marker(error)
        if unknown_key:
            answer = QMessageBox.warning(
                self,
                "Verificación de identidad SSH",
                "La reconexión recibió una clave de host que no está "
                "registrada.\n\n"
                f"Servidor: {unknown_key['hostname']}\n"
                f"Algoritmo: {unknown_key['key_type']}\n"
                f"Huella: {unknown_key['fingerprint']}\n\n"
                "Verifica la huella con el administrador antes de "
                "confiar. ¿Guardar esta clave y reintentar?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    trust_host_key(
                        KNOWN_HOSTS_FILE,
                        unknown_key["hostname"],
                        unknown_key["key_type"],
                        unknown_key["key_base64"],
                    )
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "Clave SSH",
                        compact_error(exc)
                    )
                    return
                self.reconnect_session_tab(tab)
            return

        mismatch = parse_mismatch_marker(error)
        if mismatch:
            QMessageBox.critical(
                self,
                "ALERTA: clave SSH cambió",
                "MobHector bloqueó la reconexión porque la identidad SSH "
                "del servidor cambió.\n\n"
                f"Servidor: {mismatch['hostname']}\n"
                f"Esperada: {mismatch['expected_fingerprint']}\n"
                f"Recibida: {mismatch['got_fingerprint']}\n\n"
                "No reintentes hasta verificar la huella con el administrador."
            )
            self.status.showMessage(
                "Reconexión bloqueada por cambio de clave SSH"
            )
            return

        lower = str(error).casefold()
        if (
            tab.session.get("auth_mode") == "password"
            and ("authentication" in lower or "auth" in lower)
        ):
            tab.connection.clear_password_cache()
            if tab.session.get("remember_password"):
                try:
                    credential_delete_password(tab.session)
                except CredentialStoreError as exc:
                    LOGGER.warning(
                        "No se pudo borrar contraseña rechazada: %s",
                        exc
                    )

            retry = self._prompt_password(
                tab.session,
                "Actualizar contraseña SSH"
            )
            if retry is not None:
                self.reconnect_session_tab(
                    tab,
                    password=retry
                )
            return

        self.status.showMessage(
            "No fue posible reconectar. Presiona R para reintentar o Q para cerrar."
        )

    def close_session_widget(self, tab):
        """Cierra la sesión correcta esté acoplada, desacoplada o en MultiExec."""
        if not isinstance(tab, SessionTerminal):
            return

        if tab in self.detached_windows:
            window = self.detached_windows.get(tab)
            title = window.tab_title if window else tab.session.get("name", "SSH")
            self.close_detached_session(tab, title)
            return

        if self.multi_exec_active and any(
            entry_tab is tab for _, entry_tab, _ in self.multi_exec_entries
        ):
            self.stop_multi_exec()

        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.close_tab(idx)

    def persist_startup_command_for_tab(self, tab, value):
        """Persiste Startup Command sin depender de la copia runtime de la sesión."""
        if not isinstance(tab, SessionTerminal):
            return

        value = str(value or "").strip()[:12000]
        sessions = self.config.get("sessions", [])
        idx = tab.session.get("_persist_config_index")
        identity = tab.session.get("_persist_identity")

        def saved_identity(saved):
            return [
                str(saved.get("name", "")),
                str(saved.get("host", "")),
                int(saved.get("port", 22) or 22),
                str(saved.get("username", "")),
                str(saved.get("auth_mode", "")),
                str(saved.get("key_file", "")),
            ]

        try:
            idx = int(idx) if idx is not None else None
        except (TypeError, ValueError):
            idx = None

        # El índice se usa sólo si todavía apunta a la misma identidad. Esto
        # evita modificar otra sesión si el usuario borró/reordenó entradas
        # mientras esta pestaña seguía abierta.
        if (
            idx is not None
            and 0 <= idx < len(sessions)
            and (not identity or saved_identity(sessions[idx]) == identity)
        ):
            sessions[idx]["startup_command"] = value
            save_config(self.config)
            self.status.showMessage(
                "Startup Command actualizado en la sesión guardada", 3500
            )
            return

        credential_id = str(
            tab.session.get("_persist_credential_id")
            or tab.session.get("credential_id")
            or ""
        ).strip()
        if credential_id:
            for saved in sessions:
                if str(saved.get("credential_id", "")).strip() == credential_id:
                    saved["startup_command"] = value
                    save_config(self.config)
                    self.status.showMessage(
                        "Startup Command actualizado en la sesión guardada", 3500
                    )
                    return


        if identity:
            matches = [saved for saved in sessions if saved_identity(saved) == identity]
            if len(matches) == 1:
                matches[0]["startup_command"] = value
                save_config(self.config)
                self.status.showMessage(
                    "Startup Command actualizado en la sesión guardada", 3500
                )
                return

        # Quick Connect/Platon temporal: se mantiene sólo en la pestaña actual.
        self.status.showMessage(
            "Startup Command actualizado sólo para esta pestaña temporal", 4500
        )

    def refresh_current(self):
        tab = self.current_session_tab()
        if tab:
            tab.side_panel.remote.refresh()
            tab.side_panel.local.refresh()
            self.status.showMessage("Actualizado")

    def current_terminal_tab(self):
        widget = self.tabs.currentWidget()

        if isinstance(
            widget,
            (SessionTerminal, LocalShellTerminal)
        ):
            return widget

        return self.current_session_tab()

    def attached_terminal_entries(self):
        """Terminales interactivas acopladas: SSH + Local Shell."""
        result = []

        for index in range(1, self.tabs.count()):
            widget = self.tabs.widget(index)

            if isinstance(
                widget,
                (SessionTerminal, LocalShellTerminal)
            ):
                result.append(
                    (
                        index,
                        widget,
                        self.tabs.tabText(index)
                    )
                )

        return result

    def attached_session_entries(self):
        """Sólo sesiones SSH acopladas."""
        return [
            entry
            for entry in self.attached_terminal_entries()
            if isinstance(entry[1], SessionTerminal)
        ]

    def all_terminal_tabs(self):
        """Terminales vivas: normales, MultiExec y desacopladas."""
        result = []
        seen = set()

        for _, tab, _ in self.attached_terminal_entries():
            if id(tab) not in seen:
                seen.add(id(tab))
                result.append(tab)

        if self.multi_exec_page is not None:
            for _, tab, _ in self.multi_exec_entries:
                if (
                    isinstance(
                        tab,
                        (SessionTerminal, LocalShellTerminal)
                    )
                    and id(tab) not in seen
                ):
                    seen.add(id(tab))
                    result.append(tab)

        for tab in self.detached_windows.keys():
            if (
                isinstance(
                    tab,
                    (SessionTerminal, LocalShellTerminal)
                )
                and id(tab) not in seen
            ):
                seen.add(id(tab))
                result.append(tab)

        return result

    def all_session_tabs(self):
        """Todas las sesiones SSH, incluidas MultiExec/desacopladas."""
        return [
            tab
            for tab in self.all_terminal_tabs()
            if isinstance(tab, SessionTerminal)
        ]

    def all_local_shell_tabs(self):
        """Todos los Local Shell, incluidos MultiExec/desacoplados."""
        return [
            tab
            for tab in self.all_terminal_tabs()
            if isinstance(tab, LocalShellTerminal)
        ]

    def current_session_tab(self):
        widget = self.tabs.currentWidget()

        if isinstance(widget, SessionTerminal):
            return widget

        return (
            self.last_session_tab
            if isinstance(
                self.last_session_tab,
                SessionTerminal
            )
            else None
        )

    # ---------------- MultiExec / detachable tabs ----------------

    def toggle_multi_exec(self, checked=False):
        if self.multi_exec_active:
            self.stop_multi_exec()
        else:
            self.start_multi_exec()

    def start_multi_exec(self):
        entries = self.attached_terminal_entries()
        if len(entries) < 2:
            self.act_multiexec.setChecked(False)
            QMessageBox.information(
                self,
                "Multi-Execution",
                "Abre al menos dos terminales acopladas (SSH o Local).\n\n"
                "Las terminales desacopladas pueden volver con "
                "'Reacoplar' antes de entrar a MultiExec."
            )
            return

        dlg = MultiExecDialog(entries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.act_multiexec.setChecked(False)
            return

        selected = dlg.selected_entries()
        if len(selected) < 2:
            self.act_multiexec.setChecked(False)
            return

        if self.config.get("confirm_multiexec", False):
            names = "\n".join(
                f"  • {tab.session.get('name', tab.session.get('host', 'SSH'))}"
                for _idx, tab, _title in selected
            )
            if (
                QMessageBox.warning(
                    self,
                    "Confirmar MultiExec",
                    "Vas a sincronizar el teclado entre estas terminales:\n\n"
                    f"{names}\n\n"
                    "Cada tecla/comando escrito en una terminal Activa "
                    "se replicará en las demás.\n\n¿Activar MultiExec?",
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                != QMessageBox.StandardButton.Yes
            ):
                self.act_multiexec.setChecked(False)
                return

        # Remover de mayor a menor índice evita desplazar los índices de
        # las otras pestañas seleccionadas.
        for original_index, tab, _title in sorted(
            selected, key=lambda x: x[0], reverse=True
        ):
            current = self.tabs.indexOf(tab)
            if current >= 0:
                self.tabs.removeTab(current)
            # MultiExecTile hará el reparent y luego show() explícito.

        self.multi_exec_entries = selected
        self.multi_exec_page = MultiExecPage(selected)
        self.multi_exec_page.stop_requested.connect(self.stop_multi_exec)

        idx = self.tabs.addTab(
            self.multi_exec_page,
            f"⚡ MultiExec ({len(selected)})"
        )
        self.tabs.setCurrentIndex(idx)
        self.multi_exec_active = True
        self.act_multiexec.setChecked(True)

        self.connection_status.setText(
            f"⚡ MULTI-EXEC • {len(selected)} sesiones"
        )
        self.status.showMessage(
            "MultiExec activo: cada tecla se replica en las terminales marcadas como Activo"
        )
        QTimer.singleShot(0, self.multi_exec_page.activate_all)
        QTimer.singleShot(120, self.multi_exec_page.activate_all)
        QTimer.singleShot(350, self.multi_exec_page.fit_all)

    def stop_multi_exec(self):
        if not self.multi_exec_active or self.multi_exec_page is None:
            self.multi_exec_active = False
            self.act_multiexec.setChecked(False)
            return

        page = self.multi_exec_page
        page_idx = self.tabs.indexOf(page)
        if page_idx >= 0:
            self.tabs.removeTab(page_idx)

        released = page.release_entries()
        # Reinserción en el orden original aproximado.
        for original_index, tab, title in sorted(
            released, key=lambda x: x[0]
        ):
            insert_at = min(max(1, original_index), self.tabs.count())
            self.tabs.insertTab(insert_at, tab, title)
            tab.show()
            QTimer.singleShot(
                80,
                lambda source=tab: source.reactivate_after_reparent(
                    "multiexec-exit",
                    focus=False
                )
            )

        self.multi_exec_active = False
        self.multi_exec_page = None
        self.multi_exec_entries = []
        self.act_multiexec.setChecked(False)
        page.deleteLater()

        # Volver a la primera terminal restaurada si existe.
        entries = self.attached_terminal_entries()
        if entries:
            first = entries[0][1]
            self.tabs.setCurrentWidget(first)

            if isinstance(first, SessionTerminal):
                self.last_session_tab = first

            QTimer.singleShot(
                100,
                first.terminal.focus_terminal
            )

        self.status.showMessage("MultiExec desactivado")

    def handle_multi_exec_input(self, source_tab, data):
        if not self.multi_exec_active or self.multi_exec_page is None:
            return

        active_tabs = self.multi_exec_page.enabled_tabs()
        if source_tab not in active_tabs:
            # Terminal desactivada: sus teclas sólo afectan su propio PTY.
            return

        delivered = 0
        for target in active_tabs:
            if target is source_tab:
                continue
            try:
                if target.terminal.send_multi_exec_input(data):
                    delivered += 1
            except Exception:
                LOGGER.exception("Fallo replicando entrada MultiExec")

        if delivered and data in ("\r", "\n"):
            self.status.showMessage(
                f"MultiExec: comando enviado a {delivered + 1} sesiones",
                1200
            )

    def handle_multi_exec_paste(self, source_tab, data):
        """Replica un pegado como bloque a todas las sesiones Activas."""
        if (
            not self.multi_exec_active
            or self.multi_exec_page is None
            or not data
        ):
            return

        active_tabs = self.multi_exec_page.enabled_tabs()
        if source_tab not in active_tabs:
            return

        delivered = 1  # el origen ya recibió el bloque

        for target in active_tabs:
            if target is source_tab:
                continue
            try:
                if target.terminal.send_multi_exec_paste(data):
                    delivered += 1
            except Exception:
                LOGGER.exception("Fallo replicando pegado MultiExec")

        if delivered > 1:
            self.status.showMessage(
                f"MultiExec: pegado enviado a {delivered} sesiones",
                1800
            )

    def tab_context_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        if index < 0:
            return

        widget = self.tabs.widget(index)
        menu = QMenu(self)

        if isinstance(widget, LocalShellTerminal):
            detach = menu.addAction(
                "Desacoplar en nueva ventana"
            )
            detach.setShortcut(
                QKeySequence("Ctrl+Shift+D")
            )
            restart = menu.addAction(
                "Reiniciar terminal local"
            )
            close = menu.addAction(
                "Cerrar terminal local"
            )
            chosen = menu.exec(
                self.tabs.tabBar().mapToGlobal(pos)
            )

            if chosen == detach:
                self.detach_tab(index)
            elif chosen == restart:
                widget.restart_shell()
            elif chosen == close:
                self.close_tab(index)
            return

        if isinstance(widget, SessionTerminal):
            detach = menu.addAction("Desacoplar en nueva ventana")
            detach.setShortcut(QKeySequence("Ctrl+Shift+D"))
            close = menu.addAction("Cerrar sesión")
            chosen = menu.exec(self.tabs.tabBar().mapToGlobal(pos))
            if chosen == detach:
                self.detach_tab(index)
            elif chosen == close:
                self.close_tab(index)
            return

        if isinstance(widget, MultiExecPage):
            stop = menu.addAction("Salir de MultiExec")
            chosen = menu.exec(self.tabs.tabBar().mapToGlobal(pos))
            if chosen == stop:
                self.stop_multi_exec()
            return

    def show_detach_preview(self, active, title):
        if active:
            self.status.showMessage(
                f"↗ Suelta el mouse para desacoplar: {title}"
            )
        else:
            self.status.clearMessage()

    def detach_tab_by_drag(self, widget, global_pos):
        """
        El índice se calcula al soltar, porque QTabBar pudo reordenar la
        pestaña durante el arrastre.
        """
        index = self.tabs.indexOf(widget)

        if index <= 0:
            return

        if not isinstance(
            widget,
            (SessionTerminal, LocalShellTerminal)
        ):
            self.status.showMessage(
                "Sólo las terminales SSH/Local pueden desacoplarse",
                3000
            )
            return

        self.detach_tab(
            index,
            global_pos=global_pos
        )

    def _position_detached_window(self, window, global_pos):
        if global_pos is None:
            return

        try:
            screen = QApplication.screenAt(global_pos)
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return

            available = screen.availableGeometry()

            width = min(
                max(window.width(), 900),
                max(800, available.width() - 40)
            )
            height = min(
                max(window.height(), 620),
                max(520, available.height() - 40)
            )
            window.resize(width, height)

            # Abrir cerca del punto de drop y mantenerla en la pantalla.
            x = global_pos.x() - 110
            y = global_pos.y() - 24

            x = max(
                available.left(),
                min(
                    x,
                    available.right() - width + 1
                )
            )
            y = max(
                available.top(),
                min(
                    y,
                    available.bottom() - height + 1
                )
            )

            window.move(x, y)

        except Exception:
            LOGGER.exception(
                "No se pudo posicionar ventana desacoplada"
            )

    def detach_current_session(self):
        index = self.tabs.currentIndex()
        self.detach_tab(index)

    def detach_tab(self, index, global_pos=None):
        if index <= 0 or index >= self.tabs.count():
            return
        tab = self.tabs.widget(index)
        if not isinstance(
            tab,
            (SessionTerminal, LocalShellTerminal)
        ):
            self.status.showMessage(
                "Sólo las terminales SSH/Local se pueden desacoplar"
            )
            return

        title = self.tabs.tabText(index)
        was_current = self.tabs.currentIndex() == index
        self.tabs.removeTab(index)

        # El desacople debe ser transaccional. Si la ventana independiente no
        # puede construirse por cualquier excepción, la pestaña se devuelve
        # inmediatamente al QTabWidget y nunca "desaparece" de la interfaz.
        try:
            window = DetachedSessionWindow(tab, title, self)
            window.reattach_requested.connect(self.reattach_detached_session)
            window.close_session_requested.connect(self.close_detached_session)
            self.detached_windows[tab] = window

            if global_pos is not None:
                self._position_detached_window(
                    window,
                    global_pos
                )

            window.show()
            window.raise_()
            window.activateWindow()

        except Exception as exc:
            LOGGER.exception(
                "No se pudo desacoplar la pestaña; restaurando en la ventana principal"
            )
            self.detached_windows.pop(tab, None)
            restore_index = max(1, min(index, self.tabs.count()))
            restored = self.tabs.insertTab(restore_index, tab, title)
            if was_current or self.tabs.currentIndex() <= 0:
                self.tabs.setCurrentIndex(restored)
            tab.setVisible(True)
            tab.show()
            try:
                tab.reactivate_after_reparent(
                    "detach-rollback",
                    focus=True
                )
            except Exception:
                LOGGER.debug(
                    "No se pudo reactivar terminal tras rollback de desacople",
                    exc_info=True
                )
            QMessageBox.critical(
                self,
                "Desacoplar pestaña",
                "No se pudo abrir la ventana independiente. La pestaña fue "
                "restaurada automáticamente.\n\n" + compact_error(exc)
            )
            self.status.showMessage(
                f"No se pudo desacoplar {title}; pestaña restaurada",
                5000
            )
            return

        self.status.showMessage(
            f"{title} desacoplada en una ventana independiente",
            3500
        )

    def reattach_detached_session(self, tab, title):
        window = self.detached_windows.pop(tab, None)
        if window is None:
            return

        window.take_session_widget()
        index = self.tabs.addTab(tab, title)
        self.tabs.setCurrentIndex(index)

        if isinstance(tab, SessionTerminal):
            self.last_session_tab = tab
            self.side_stack.setCurrentWidget(
                tab.side_panel
            )
        else:
            self.side_stack.setCurrentWidget(
                self.sftp_placeholder
            )

        tab.show()
        window.hide()
        window.deleteLater()

        QTimer.singleShot(
            50,
            lambda: tab.reactivate_after_reparent(
                "detached-reattach",
                focus=True
            )
        )
        self.status.showMessage(f"{title} reacoplada")

    def reattach_all_detached(self):
        for tab, window in list(self.detached_windows.items()):
            self.reattach_detached_session(tab, window.tab_title)

    def close_detached_session(self, tab, title):
        window = self.detached_windows.pop(tab, None)
        if window is None:
            return

        window._closing_session = True
        window.take_session_widget()

        if isinstance(tab, SessionTerminal):
            self._remove_session_side_panel(tab)

        try:
            tab.close_session()
        except Exception:
            LOGGER.exception(
                "Error cerrando terminal desacoplada"
            )

        tab.deleteLater()
        window.close()
        window.deleteLater()
        self.status.showMessage(
            f"Terminal {title} cerrada"
        )

    def _remove_session_side_panel(self, tab):
        if self.side_stack.currentWidget() is tab.side_panel:
            self.side_stack.setCurrentWidget(self.sftp_placeholder)
        self.side_stack.removeWidget(tab.side_panel)
        tab.side_panel.setParent(None)

    # ---------------- tabs/editor ----------------

    def open_editor(self, connection, path, title):
        editor = RemoteEditor(connection, path, self.pool)
        idx = self.tabs.addTab(editor, f"✎ {title}")
        self.tabs.setCurrentIndex(idx)

    def close_tab(self, idx):
        if idx == 0:
            return
        w = self.tabs.widget(idx)

        if isinstance(w, MultiExecPage):
            self.stop_multi_exec()
            return

        if isinstance(w, RemoteEditor) and w.changed:
            if QMessageBox.question(
                self, "Editor", "Hay cambios sin guardar. ¿Cerrar?"
            ) != QMessageBox.StandardButton.Yes:
                return

        if isinstance(w, LocalShellTerminal):
            self.config["terminal_zoom"] = (
                w.terminal.zoom_percent
            )
            save_config(self.config)
            w.close_session()

        if isinstance(w, SessionTerminal):
            if (
                self.config.get("confirm_close_session", True)
                and w.is_connected()
                and QMessageBox.question(
                    self,
                    "Cerrar sesión SSH",
                    f"¿Cerrar la sesión conectada "
                    f"{w.session.get('name', w.session.get('host', 'SSH'))}?"
                )
                != QMessageBox.StandardButton.Yes
            ):
                return

            self.config["last_local_path"] = (
                w.side_panel.local.current_path
            )
            self.config["terminal_zoom"] = w.terminal.zoom_percent
            self.config["workspace_files_visible"] = (
                self.sftp_dock.isVisible()
            )
            save_config(self.config)

            self._remove_session_side_panel(w)

            w.close_session()
            if self.last_session_tab is w:
                self.last_session_tab = None

        self.tabs.removeTab(idx)
        w.deleteLater()

    def current_tab_changed(self, idx):
        w = self.tabs.widget(idx)

        if isinstance(w, LocalShellTerminal):
            self.side_stack.setCurrentWidget(
                self.sftp_placeholder
            )
            self.sftp_dock.setWindowTitle(
                "SFTP / Archivos — no disponible en Local Shell"
            )
            self.connection_status.setText(
                f">_ LOCAL • {w.display_name}"
            )
            self.zoom_indicator.setText(
                f" {w.terminal.zoom_percent}% "
            )
            self.backdrop.refresh_after_session_open()
            QTimer.singleShot(
                0,
                lambda source=w:
                    source.reactivate_after_reparent(
                        "local-shell-selected",
                        focus=False
                    )
            )

        elif isinstance(w, SessionTerminal):
            self.last_session_tab = w

            self.side_stack.setCurrentWidget(w.side_panel)
            self.sftp_dock.setWindowTitle(
                f"SFTP / Archivos — "
                f"{w.session.get('name', w.session['host'])}"
            )

            self.connection_status.setText(
                (
                    f"⚡ PLATON • "
                    f"{w.session['username']}@"
                    f"{w.session['host']}:"
                    f"{w.session.get('port', 22)}"
                    if w.session.get("auth_mode") == "platon_none"
                    else
                    f"● {w.session['username']}@{w.session['host']}"
                )
            )
            self.zoom_indicator.setText(
                f" {w.terminal.zoom_percent}% "
            )
            self.backdrop.refresh_after_session_open()
            QTimer.singleShot(
                0,
                lambda source=w: source.reactivate_after_reparent(
                    "normal-tab-selected",
                    focus=False
                )
            )

        elif isinstance(w, MultiExecPage):
            active = len(w.enabled_tabs())
            self.connection_status.setText(
                f"⚡ MULTI-EXEC • {active}/{len(w.tiles)} activas"
            )
            QTimer.singleShot(0, w.activate_all)

        elif idx == 0:
            self.connection_status.setText("Sin conexión")

    # ---------------- workspace / appearance ----------------

    def toggle_current_files(self):
        if self.sftp_dock.isVisible():
            self.sftp_dock.hide()
        else:
            tab = self.current_session_tab()
            if tab:
                self.side_stack.setCurrentWidget(tab.side_panel)
                self.sftp_dock.setWindowTitle(
                    f"SFTP / Archivos — "
                    f"{tab.session.get('name', tab.session['host'])}"
                )
            self.sftp_dock.show()
            self.sftp_dock.raise_()

        self.config["workspace_files_visible"] = (
            self.sftp_dock.isVisible()
        )

    def workspace_files_visibility_changed(self, visible):
        # Compatibilidad con configuración de versiones previas.
        self.config["workspace_files_visible"] = bool(visible)

    def reset_panel_layout(self):
        # Sacar paneles de modo flotante si aplica.
        self.sessions_dock.setFloating(False)
        self.sftp_dock.setFloating(False)
        self.transfers.setFloating(False)

        # Reinsertarlos en las áreas previstas.
        self.removeDockWidget(self.sessions_dock)
        self.removeDockWidget(self.sftp_dock)
        self.removeDockWidget(self.transfers)

        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea,
            self.sessions_dock
        )
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea,
            self.sftp_dock
        )
        self.tabifyDockWidget(
            self.sessions_dock,
            self.sftp_dock
        )

        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea,
            self.transfers
        )

        self.sessions_dock.show()
        self.sftp_dock.show()
        self.sessions_dock.raise_()

        # Un ancho útil sin quitarle comodidad a la terminal.
        self.resizeDocks(
            [self.sessions_dock, self.sftp_dock],
            [420, 420],
            Qt.Orientation.Horizontal
        )
        self.resizeDocks(
            [self.transfers],
            [175],
            Qt.Orientation.Vertical
        )
        self.transfers.hide()

        self.status.showMessage(
            "Paneles restablecidos: terminal central + docks laterales"
        )

    def open_windows_credentials(self):
        """Abre el panel nativo de Credential Manager de Windows."""
        if os.name != "nt":
            QMessageBox.information(
                self,
                "Credenciales de Windows",
                "Esta opción sólo está disponible en Windows."
            )
            return

        try:
            QProcess.startDetached(
                "control.exe",
                ["/name", "Microsoft.CredentialManager"]
            )
        except Exception:
            LOGGER.exception(
                "No se pudo abrir Windows Credential Manager"
            )
            QMessageBox.warning(
                self,
                "Credenciales de Windows",
                "No se pudo abrir el Administrador de credenciales."
            )

    def open_config_folder(self):
        ensure_config_dir()
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(CONFIG_DIR))
        )

    def open_log_folder(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(LOG_DIR))
        )

    def reset_preferences(self):
        if (
            QMessageBox.question(
                self,
                "Restablecer preferencias",
                "Se restablecerán apariencia, terminal, paneles y ajustes SSH "
                "a sus valores recomendados.\\n\\n"
                "Las sesiones guardadas, contraseñas de Windows y claves "
                "SSH conocidas NO se eliminarán.\\n\\n¿Continuar?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        defaults = _default_config()
        preserve = {
            "sessions": self.config.get("sessions", []),
            "last_local_path": self.config.get(
                "last_local_path", safe_local_start()
            ),
        }

        self.config.clear()
        self.config.update(defaults)
        self.config.update(preserve)
        save_config(self.config)

        self.apply_appearance()
        self.apply_terminal_preferences()
        self.apply_general_preferences(initial=False)

        self.status.showMessage(
            "Preferencias restablecidas; sesiones conservadas",
            5000
        )

    def terminal_runtime_preferences(self):
        return {
            "font_family": self.config.get(
                "terminal_font_family", "Cascadia Mono"
            ),
            "font_size": int(
                self.config.get("terminal_font_size", 14)
            ),
            "cursor_style": self.config.get(
                "terminal_cursor_style", "block"
            ),
            "cursor_blink": bool(
                self.config.get("terminal_cursor_blink", True)
            ),
            "scrollback": int(
                self.config.get("terminal_scrollback", 500000)
            ),
            "history_sticky": bool(
                self.config.get("terminal_history_sticky", True)
            ),
            "protect_scrollback": bool(
                self.config.get("terminal_protect_scrollback", True)
            ),
            "selection_autoscroll": bool(
                self.config.get("terminal_selection_autoscroll", True)
            ),
            "line_height": int(
                self.config.get("terminal_line_height", 108)
            ),
            "bold_bright": bool(
                self.config.get("terminal_bold_bright", True)
            ),
            "click_to_cursor": bool(
                self.config.get("terminal_click_to_cursor", True)
            ),
            "tui_native_mouse": bool(
                self.config.get("terminal_tui_native_mouse", True)
            ),
            "tui_arrow_fallback": bool(
                self.config.get("terminal_tui_arrow_fallback", True)
            ),
            "middle_click_paste": bool(
                self.config.get("terminal_middle_click_paste", False)
            ),
            "bell_style": self.config.get("terminal_bell_style", "none"),
            "word_mode": self.config.get("terminal_word_mode", "unix"),
            "show_scrollbar": bool(
                self.config.get("terminal_show_scrollbar", True)
            ),
        }

    def terminal_clipboard_preferences(self):
        return {
            "auto_copy_selection": bool(
                self.config.get(
                    "terminal_auto_copy_selection", True
                )
            ),
            "ctrl_v_paste": bool(
                self.config.get(
                    "terminal_ctrl_v_paste", True
                )
            ),
            "right_click_paste": bool(
                self.config.get(
                    "terminal_right_click_paste", True
                )
            ),
        }

    def open_terminal_settings(self):
        dlg = TerminalSettingsDialog(self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self.config.update(dlg.value())
        save_config(self.config)
        self.apply_terminal_preferences()

        self.status.showMessage(
            "Configuración de terminal actualizada",
            3000
        )

    def apply_terminal_preferences(self):
        clipboard = self.terminal_clipboard_preferences()
        runtime = self.terminal_runtime_preferences()

        for tab in self.all_terminal_tabs():
            try:
                tab.terminal.set_clipboard_preferences(clipboard)
                tab.terminal.set_terminal_preferences(runtime)
            except Exception:
                LOGGER.exception(
                    "No se pudieron aplicar preferencias de terminal"
                )

    def apply_terminal_clipboard_preferences(self):
        # Alias de compatibilidad interna.
        self.apply_terminal_preferences()

    def open_general_settings(self):
        dlg = GeneralSettingsDialog(self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self.config.update(dlg.value())
        save_config(self.config)
        self.apply_general_preferences(initial=False)

        # Actualizar health check de sesiones ya abiertas.
        interval = max(
            2,
            int(self.config.get("ssh_health_interval", 5))
        ) * 1000
        for tab in self.all_session_tabs():
            try:
                tab.health_timer.setInterval(interval)
                tab.connection.session["_ssh_keepalive"] = int(
                    self.config.get("ssh_keepalive", 20)
                )
                tab.connection.session["_ssh_connect_timeout"] = int(
                    self.config.get("ssh_connect_timeout", 12)
                )
                tab.connection.session["_ssh_auth_timeout"] = int(
                    self.config.get("ssh_auth_timeout", 15)
                )
                tab.connection.session["_ssh_health_interval"] = int(
                    self.config.get("ssh_health_interval", 5)
                )
                tab.connection.session["_auto_focus_terminal"] = bool(
                    self.config.get("auto_focus_terminal", True)
                )
                tab.connection.session["_ssh_compression"] = bool(
                    self.config.get("ssh_compression", False)
                )
                tab.connection.session["_auto_reconnect"] = bool(
                    self.config.get("auto_reconnect", False)
                )
                tab.connection.session["_auto_reconnect_attempts"] = int(
                    self.config.get("auto_reconnect_attempts", 3)
                )
                tab.connection.session["_auto_reconnect_delay"] = int(
                    self.config.get("auto_reconnect_delay", 3)
                )
                tab._auto_reconnect_enabled = bool(
                    self.config.get("auto_reconnect", False)
                )
                tab._auto_reconnect_total = int(
                    self.config.get("auto_reconnect_attempts", 3)
                )
                tab._auto_reconnect_left = tab._auto_reconnect_total
                tab._auto_reconnect_delay = int(
                    self.config.get("auto_reconnect_delay", 3)
                )
                tab.side_panel.remote.hidden.setChecked(
                    bool(self.config.get("sftp_show_hidden_default", True))
                )
                tab.session["_sftp_follow_terminal_folder"] = bool(
                    self.config.get("sftp_follow_terminal_folder", True)
                )
                tab.connection.session["_sftp_follow_terminal_folder"] = bool(
                    self.config.get("sftp_follow_terminal_folder", True)
                )
            except Exception:
                LOGGER.exception("No se pudo actualizar sesión abierta")

        self.status.showMessage(
            "Preferencias generales actualizadas",
            3500
        )

    def apply_general_preferences(self, initial=False):
        threads = max(
            2,
            min(16, int(self.config.get("worker_threads", 8)))
        )
        self.pool.setMaxThreadCount(threads)

        LOGGER.setLevel(
            getattr(
                logging,
                str(self.config.get("log_level", "INFO")).upper(),
                logging.INFO
            )
        )

        dock_options = (
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.AllowTabbedDocks
        )
        if self.config.get("animated_docks", True):
            dock_options |= QMainWindow.DockOption.AnimatedDocks
        self.setDockOptions(dock_options)

        if not self.zen_mode:
            self.main_toolbar.setVisible(
                bool(self.config.get("show_toolbar", True))
            )
            self.statusBar().setVisible(
                bool(self.config.get("show_statusbar", True))
            )

        self.tabs.setTabPosition(
            QTabWidget.TabPosition.South
            if self.config.get("tab_position", "top") == "bottom"
            else QTabWidget.TabPosition.North
        )
        self.tabs.setTabsClosable(
            bool(self.config.get("show_tab_close_buttons", True))
        )

        detach_distance = max(
            30, min(220, int(self.config.get("detach_distance", 70)))
        )
        self.main_tab_bar.DETACH_VERTICAL_MARGIN = detach_distance
        self.main_tab_bar.DETACH_HORIZONTAL_MARGIN = detach_distance + 40

        if initial:
            self.sessions_dock.setVisible(
                bool(self.config.get("show_sessions_panel", True))
            )

            # SFTP se muestra al conectar si así está configurado.
            if not self.all_session_tabs():
                self.sftp_dock.hide()

    def open_appearance(self):
        dlg = AppearanceDialog(self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.config.update(dlg.value())
        save_config(self.config)
        self.apply_appearance()

    def apply_appearance(self):
        mode = self.config.get("appearance_mode", "dark")
        self.backdrop.configure(
            mode,
            self.config.get("background_image", ""),
            self.config.get("background_blur", 18),
            self.config.get("glass_darkness", 68),
        )

        app = QApplication.instance()
        app.setPalette(palette_for_mode(mode))

        if mode == "glass":
            base_css = QSS + GLASS_QSS
        elif mode == "light":
            base_css = QSS + LIGHT_QSS
        elif mode in ("coffee", "sepia"):
            base_css = QSS + COFFEE_QSS
        else:
            base_css = QSS

        app.setStyleSheet(
            base_css
            + appearance_overlay_qss(
                mode,
                self.config.get("accent_color", "cyan"),
                self.config.get("ui_density", "normal"),
            )
        )

        terminal_theme = self.config.get("terminal_theme", "follow")
        for w in self.all_terminal_tabs():
            w.set_visual_mode(
                mode,
                terminal_theme,
                background_image=self.config.get(
                    "background_image", ""
                ),
                background_blur=self.config.get(
                    "background_blur", 18
                ),
                glass_darkness=self.config.get(
                    "glass_darkness", 68
                ),
            )

        for window in list(self.detached_windows.values()):
            try:
                window.sync_appearance()
            except Exception:
                LOGGER.exception("No se pudo actualizar apariencia desacoplada")

    # ---------------- zoom/dynamic layout ----------------

    def terminal_zoom_changed(self, zoom):
        self.config["terminal_zoom"] = zoom
        if hasattr(self, "zoom_indicator") and self.zoom_indicator is not None:
            self.zoom_indicator.setText(f" {zoom}% ")

    def zoom_terminal_in(self):
        tab = self.current_terminal_tab()
        if tab:
            tab.terminal.zoom_in_custom()

    def zoom_terminal_out(self):
        tab = self.current_terminal_tab()
        if tab:
            tab.terminal.zoom_out_custom()

    def zoom_terminal_reset(self):
        tab = self.current_terminal_tab()
        if tab:
            tab.terminal.zoom_reset_custom()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def toggle_zen(self):
        entering = not self.zen_mode

        if entering:
            self._zen_restore = {
                "sessions": self.sessions_dock.isVisible(),
                "sftp": self.sftp_dock.isVisible(),
                "transfers": self.transfers.isVisible(),
                "toolbar": self.main_toolbar.isVisible(),
                "status": self.statusBar().isVisible(),
                "menubar": self.menuBar().isVisible(),
            }
            self.zen_mode = True
            self.sessions_dock.hide()
            self.sftp_dock.hide()
            self.transfers.hide()
            self.main_toolbar.hide()
            self.statusBar().hide()
            self.menuBar().hide()
            tab = self.current_terminal_tab()
            if tab:
                QTimer.singleShot(
                    50,
                    tab.terminal.focus_terminal
                )
        else:
            self.zen_mode = False
            state = getattr(self, "_zen_restore", {})
            self.sessions_dock.setVisible(
                state.get("sessions", True)
            )
            self.sftp_dock.setVisible(
                state.get("sftp", True)
            )
            self.transfers.setVisible(
                state.get("transfers", False)
            )
            self.main_toolbar.setVisible(state.get("toolbar", True))
            self.statusBar().setVisible(state.get("status", True))
            self.menuBar().setVisible(True)
            tab = self.current_terminal_tab()
            if tab:
                QTimer.singleShot(
                    50,
                    tab.terminal.focus_terminal
                )

    # ---------------- state ----------------

    def restore_ui_state(self):
        restore_layout = bool(
            self.config.get("restore_window_layout", True)
        )

        geometry = (
            self.settings.value("geometry_mobhector_1")
            if restore_layout
            else None
        )
        state = (
            self.settings.value("windowState_mobhector_1")
            if restore_layout
            else None
        )

        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

        self.transfers.hide()
        QTimer.singleShot(0, self.transfers.hide)
        QTimer.singleShot(150, self.transfers.hide)

        if (
            self.config.get("start_maximized", True)
            and (not geometry or not restore_layout)
        ):
            QTimer.singleShot(0, self.showMaximized)

    def save_ui_state(self):
        self.settings.setValue("geometry_mobhector_1", self.saveGeometry())
        self.settings.setValue("windowState_mobhector_1", self.saveState())

    # ---------------- misc ----------------

    def show_shortcuts(self):
        QMessageBox.information(
            self, "Atajos",
            "Ctrl+N  Nueva sesión\n"
            "Ctrl+Shift+T  Abrir conexión en pestaña\n"
            "Ctrl+R  Reconectar\n"
            "F5  Actualizar SFTP\n\n"
            "Ctrl + rueda  Zoom del terminal\n"
            "Ctrl++ / Ctrl+-  Zoom terminal\n"
            "Ctrl+0  Zoom 100%\n\n"
            "Ctrl+Shift+S  Mostrar/ocultar SFTP / Archivos\n"
            "Ctrl+Shift+E  Mostrar/ocultar sesiones\n"
            "Ctrl+Shift+J  Mostrar/ocultar transferencias\n"
            "Ctrl+Shift+R  Restablecer paneles\n"
            "Ctrl+Shift+M  MultiExec\n"
            "Ctrl+Shift+L  Local Shell integrado\n"
            "Ctrl+Shift+D  Desacoplar / reacoplar terminal\n"
            "F11  Pantalla completa\n"
            "Ctrl+Shift+F11  Modo Zen"
        )

    def about(self):
        AboutDialog(self).exec()

    def closeEvent(self, event):
        if self.transfers.cancel_events:
            if not getattr(self, "_closing_after_cancel", False):
                answer = QMessageBox.question(self, "Transferencias activas",
                    "Hay transferencias activas. ¿Cancelarlas y cerrar cuando terminen de limpiar temporales?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self._closing_after_cancel = True
                self.transfers.cancel_all()
            event.ignore()
            self.status.showMessage("Esperando cancelación y limpieza de transferencias…")
            QTimer.singleShot(250, self.close)
            return
        dirty_editors = [self.tabs.widget(i) for i in range(self.tabs.count())
                         if isinstance(self.tabs.widget(i), RemoteEditor) and self.tabs.widget(i).changed]
        if dirty_editors:
            answer = QMessageBox.question(self, "Cambios sin guardar",
                f"Hay {len(dirty_editors)} archivo(s) con cambios sin guardar. ¿Descartarlos y salir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                self._closing_after_cancel = False
                event.ignore()
                return
        self._app_closing = True
        if self.zen_mode:
            self.toggle_zen()
        if self.isFullScreen():
            self.showMaximized()

        self.save_ui_state()

        terminals = self.all_terminal_tabs()

        for window in list(self.detached_windows.values()):
            window._owner_closing = True

        for terminal_tab in terminals:
            try:
                terminal_tab.close_session()
            except Exception:
                LOGGER.exception(
                    "Error cerrando terminal al salir"
                )

        for window in list(self.detached_windows.values()):
            try:
                window.close()
            except Exception:
                pass
        self.detached_windows.clear()

        save_config(self.config)
        event.accept()


# ============================================================
# Theme
# ============================================================

QSS = r"""
* {
    font-family: "Segoe UI";
    font-size: 10.5pt;
}
QMainWindow, QDialog {
    background: #090b0f;
    color: #d6dce6;
}
QWidget {
    color: #d6dce6;
}
QWidget#sessionWorkspace,
QWidget#sessionFilesPanel,
QFrame#terminalContainer {
    background: #090b0f;
}
QMenuBar {
    background: #0d1015;
    color: #bcc5d1;
    border-bottom: 1px solid #202631;
}
QMenuBar::item {
    padding: 6px 10px;
}
QMenuBar::item:selected {
    background: #1a212b;
}
QMenu {
    background: #11151c;
    color: #d7dee8;
    border: 1px solid #2b3441;
}
QMenu::item {
    padding: 7px 28px 7px 10px;
}
QMenu::item:selected {
    background: #173f46;
}
QToolBar#MainToolbar {
    background: #0d1015;
    border: none;
    border-bottom: 1px solid #202631;
    spacing: 5px;
    padding: 5px;
}
QToolBar QToolButton {
    background: #131820;
    color: #cfd7e2;
    border: 1px solid #28313e;
    border-radius: 5px;
    padding: 6px 9px;
}
QToolBar QToolButton:hover {
    background: #1d2631;
    border-color: #3d4b5d;
}
QPushButton, QToolButton {
    background: #151a22;
    color: #d5dce6;
    border: 1px solid #2c3542;
    border-radius: 5px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover {
    background: #202833;
    border-color: #465468;
}
QPushButton:pressed, QToolButton:pressed {
    background: #0f1319;
}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
    background: #0c0f14;
    color: #e1e6ee;
    border: 1px solid #29313d;
    border-radius: 4px;
    padding: 5px;
    selection-background-color: #24616a;
}
QTextEdit#terminal {
    background: #030405;
    color: #d8dee9;
    border: none;
    selection-background-color: #275862;
}
QWebEngineView#xtermView {
    background: #050607;
    border: none;
}
QFrame#terminalHeader {
    background: #0a0d11;
    border-bottom: 1px solid #1e242d;
}
QListWidget, QTreeWidget, QTreeView {
    background: #0b0e13;
    alternate-background-color: #0e1117;
    color: #d2d9e3;
    border: 1px solid #242b35;
    selection-background-color: #1d4d55;
    selection-color: white;
}
QListWidget::item {
    padding: 8px 5px;
    margin: 1px 0;
}
QHeaderView::section {
    background: #11161d;
    color: #8995a7;
    border: none;
    border-right: 1px solid #242b35;
    border-bottom: 1px solid #242b35;
    padding: 6px;
}
QTabWidget::pane {
    border: none;
    background: #090b0f;
}
QTabBar::tab {
    background: #0f1319;
    color: #8d98a8;
    border: 1px solid #232a34;
    border-bottom: none;
    padding: 9px 15px;
    min-width: 105px;
}
QTabBar::tab:selected {
    background: #151b23;
    color: #71d6d1;
    border-top: 2px solid #57c9c4;
}
QTabBar::tab:hover {
    background: #171d25;
    color: #e0e5ec;
}
QDockWidget {
    color: #aeb8c6;
}
QDockWidget#SessionsDock,
QDockWidget#SftpDock,
QDockWidget#TransferDock {
    background: #090c10;
}
QStackedWidget#SftpStack {
    background: #090c10;
}
QDockWidget::title {
    background: #0f1319;
    padding: 7px 8px;
    border: 1px solid #232a34;
}
QStatusBar {
    background: #0d1015;
    color: #7f8998;
    border-top: 1px solid #202631;
}
QLabel#brand {
    color: #65d9d4;
    font-size: 15pt;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#muted {
    color: #7c8797;
}
QLabel#connectedDot {
    color: #58d68d;
}
QLabel#homeTitle {
    color: #f3f6fa;
    font-size: 31pt;
    font-weight: 700;
}
QLabel#homeSubtitle {
    color: #8792a3;
    font-size: 13pt;
}
QLabel#cardTitle {
    color: #65d9d4;
    font-size: 13pt;
    font-weight: 600;
}
QLabel#zoomIndicator {
    color: #65d9d4;
    font-family: "Cascadia Mono";
    font-weight: 600;
}
QFrame#homeCard {
    background: #0f1319;
    border: 1px solid #232b36;
    border-radius: 9px;
}
QFrame#transferActivityCard {
    background: #0d1a20;
    border: 1px solid #4a7480;
    border-radius: 9px;
}
QLabel#transferActivityIcon {
    color: #65d9d4;
    font-size: 18pt;
    font-weight: 700;
}
QLabel#transferActivityTitle {
    color: #dce8ed;
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QLabel#transferActivityPercent {
    color: #65d9d4;
    font-family: "Cascadia Mono";
    font-size: 12pt;
    font-weight: 700;
}
QLabel#transferActivityFile {
    color: #f0f4f7;
    font-family: "Cascadia Mono";
    font-size: 10pt;
    font-weight: 600;
}
QLabel#transferActivityDetail {
    color: #8f9eaa;
    font-family: "Cascadia Mono";
    font-size: 9pt;
}
QLabel#transferActivityDestination {
    color: #718391;
    font-family: "Cascadia Mono";
    font-size: 8.5pt;
}
QPushButton#transferQueueButton {
    background: #152029;
    color: #9fc6c7;
    border: 1px solid #30434c;
    padding: 4px 8px;
    font-size: 8.5pt;
}
QPushButton#transferQueueButton:hover {
    background: #1d3038;
    border-color: #4b6870;
}
QLabel#remoteFolderStatus {
    color: #748494;
    font-size: 9pt;
    padding: 1px 2px;
}
QLabel#transferSummary {
    color: #9aabb8;
    font-weight: 600;
}
QProgressBar#inlineTransferProgress {
    background: #222c35;
    color: #f2f7f8;
    border: 1px solid #33434d;
    border-radius: 6px;
    text-align: center;
    font-family: "Cascadia Mono";
    font-size: 9pt;
    font-weight: 700;
}
QProgressBar#inlineTransferProgress::chunk {
    background: #409d9a;
    border-radius: 5px;
}
QProgressBar#transferProgress {
    background: #11171d;
    border: 1px solid #28333d;
    border-radius: 4px;
    color: #cfd9df;
    text-align: center;
    font-family: "Cascadia Mono";
    font-size: 9pt;
}
QProgressBar#transferProgress::chunk {
    background: #3fa9a5;
    border-radius: 3px;
}
QTreeWidget#remoteTree {
    border: 1px solid #26303a;
}
QTreeWidget#remoteTree:focus {
    border: 1px solid #35515d;
}
QLabel#selectionStatus {
    color: #6f7f8f;
    font-size: 9pt;
    padding: 2px 4px;
}
QLabel#sessionTitle {
    color: #dce5ec;
    font-family: "Cascadia Mono";
    font-weight: 600;
}
QSplitter#workspaceSplitter::handle {
    background: #252e39;
    width: 5px;
}
QSplitter#workspaceSplitter::handle:hover {
    background: #4a626d;
}
QTabWidget#mainTabs::pane {
    background: #090b0f;
}
QScrollBar:vertical {
    background: #090b0f;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #303947;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #465366;
}
QScrollBar:horizontal {
    background: #090b0f;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #303947;
    min-width: 28px;
    border-radius: 5px;
}
QSplitter::handle {
    background: #1d232c;
}
QToolTip {
    background: #171c24;
    color: white;
    border: 1px solid #394555;
}

QFrame#multiExecBanner {
    background: #321316;
    border: 1px solid #8c343b;
    border-radius: 6px;
}
QLabel#multiExecBannerText {
    color: #ffadb3;
    font-weight: 700;
}
QFrame#multiExecTile {
    background: #080b0f;
    border: 1px solid #35404c;
    border-radius: 6px;
}
QFrame#multiExecTileHeader {
    background: #0d1218;
    border: none;
    border-bottom: 1px solid #35404c;
}
QLabel#multiExecTileTitle {
    color: #9ddbe0;
    font-weight: 600;
}
QCheckBox#multiExecEnabled {
    color: #b8e6c8;
    font-weight: 600;
}
QLabel#multiExecDialogTitle {
    color: #8dd5da;
    font-size: 16pt;
    font-weight: 700;
}

QLabel#authHint {
    background: #111a22;
    color: #a9cbd0;
    border: 1px solid #30434d;
    border-radius: 6px;
    padding: 8px 10px;
}
QLabel#authBadge {
    color: #8ebfc4;
    background: rgba(31,53,61,150);
    border: 1px solid #36545e;
    border-radius: 7px;
    padding: 2px 7px;
}
QFrame#disconnectBanner {
    background: #32191c;
    border-top: 1px solid #8c3d45;
    border-bottom: 1px solid #8c3d45;
}
QLabel#disconnectText { color: #ffd5d8; font-weight: 600; }
QPushButton#reconnectButton {
    background: #174d35; color: #d9ffea; border: 1px solid #34875f;
}
QPushButton#reconnectButton:hover { background: #206345; }
QPushButton#disconnectCloseButton {
    background: #4a2727; color: #ffe1e1; border: 1px solid #865050;
}
QPushButton#disconnectCloseButton:hover { background: #613333; }
"""


GLASS_QSS = r"""
QWidget#backdropWidget { background: transparent; }
QWidget#sessionWorkspace { background: rgba(5, 9, 13, 58); }
QWidget#sessionFilesPanel { background: rgba(7, 11, 16, 165); }
QTabWidget#mainTabs::pane { background: rgba(4, 8, 12, 52); }
QFrame#terminalContainer { background: transparent; border: none; }
QWebEngineView#xtermView { background: transparent; border: none; }
QFrame#terminalHeader { background: rgba(7, 12, 18, 168); border-bottom: 1px solid rgba(120,170,180,85); }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: rgba(9, 15, 21, 188); }
QListWidget, QTreeWidget, QTreeView { background: rgba(7,12,18,182); alternate-background-color: rgba(12,18,25,182); }
QHeaderView::section { background: rgba(15,23,31,205); }
QDockWidget#SessionsDock, QDockWidget#SftpDock, QDockWidget#TransferDock, QStackedWidget#SftpStack { background: rgba(7,11,16,176); }
QDockWidget::title { background: rgba(10,16,22,210); }
QFrame#transferActivityCard, QFrame#homeCard { background: rgba(8,17,24,198); }
QTabBar::tab { background: rgba(8,14,20,192); }
QTabBar::tab:selected { background: rgba(18,29,38,218); }
QToolTip { background: rgba(8,13,18,238); }
QFrame#multiExecBanner { background: rgba(62,17,22,214); border: 1px solid rgba(180,90,98,180); }
QFrame#multiExecTile { background: rgba(5,10,14,100); border-color: rgba(104,151,160,125); }
QFrame#multiExecTileHeader { background: rgba(7,14,19,190); border:none; border-bottom:1px solid rgba(104,151,160,125); }

QLabel#authHint { background: rgba(7,14,19,205); color: #b8dadd; }
QLabel#authBadge { background: rgba(16,40,48,190); }
QFrame#disconnectBanner {
    background: rgba(62,19,25,220);
    border-top: 1px solid rgba(218,89,102,180);
    border-bottom: 1px solid rgba(218,89,102,180);
}
"""

LIGHT_QSS = r"""
QMainWindow, QDialog, QWidget { background: #f3f6f9; color: #17212b; }
QWidget#backdropWidget { background: #eef2f6; }
QWidget#sessionWorkspace, QWidget#sessionFilesPanel, QFrame#terminalContainer, QTabWidget#mainTabs::pane, QStackedWidget#SftpStack { background: #f8fafc; }
QMenuBar { background:#fff; color:#1f2a35; border-bottom:1px solid #cbd5df; }
QMenuBar::item:selected { background:#e8eef4; color:#101820; }
QMenu { background:#fff; color:#17212b; border:1px solid #c7d1db; }
QMenu::item:selected { background:#d9eef1; color:#0d3338; }
QToolBar#MainToolbar { background:#fff; border-bottom:1px solid #cbd5df; }
QToolBar QToolButton, QPushButton, QToolButton { background:#fff; color:#17212b; border:1px solid #bdc9d4; }
QToolBar QToolButton:hover, QPushButton:hover, QToolButton:hover { background:#eaf1f6; color:#0d1720; border-color:#9fb0be; }
QPushButton:pressed, QToolButton:pressed { background:#dfe8ef; }
QStatusBar { background:#fff; color:#435260; border-top:1px solid #cbd5df; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background:#fff; color:#111a22; border:1px solid #b9c6d1; selection-background-color:#9dd9de; selection-color:#07171a; }
QComboBox QAbstractItemView { background:#fff; color:#17212b; selection-background-color:#d5edf0; selection-color:#102529; }
QCheckBox { color:#1c2731; }
QListWidget, QTreeWidget, QTreeView { background:#fff; alternate-background-color:#f1f5f8; color:#111a22; border:1px solid #c2cdd7; selection-background-color:#b9e4e7; selection-color:#0c2023; }
QTreeWidget#remoteTree { border:1px solid #b8c5cf; }
QTreeWidget#remoteTree:focus { border:1px solid #4a9da3; }
QHeaderView::section { background:#e8eef3; color:#263645; border:none; border-right:1px solid #c4ced7; border-bottom:1px solid #c4ced7; }
QTabWidget::pane, QTabWidget#mainTabs::pane { background:#f8fafc; border:none; }
QTabBar::tab { background:#e5ebf0; color:#42515f; border:1px solid #c4ced7; border-bottom:none; }
QTabBar::tab:selected { background:#fff; color:#0c5f64; border-top:2px solid #22888e; }
QTabBar::tab:hover { background:#edf3f6; color:#17212b; }
QDockWidget { color:#1f2b36; }
QDockWidget#SessionsDock, QDockWidget#SftpDock, QDockWidget#TransferDock { background:#f8fafc; }
QDockWidget::title { background:#e7edf2; color:#22313d; border:1px solid #c4ced7; }
QFrame#terminalHeader { background:#e8eef3; border-bottom:1px solid #c3ced8; }
QWebEngineView#xtermView { background:#f7f9fc; border:none; }
QFrame#homeCard { background:#fff; border:1px solid #c3ced8; }
QLabel#brand { color:#116d72; } QLabel#homeTitle { color:#13202b; } QLabel#homeSubtitle { color:#536575; } QLabel#cardTitle { color:#0e686d; } QLabel#muted { color:#536575; } QLabel#connectedDot { color:#18794e; } QLabel#zoomIndicator { color:#0c6f74; } QLabel#sessionTitle { color:#182734; }
QFrame#transferActivityCard { background:#fff; border:1px solid #9eb5bf; }
QLabel#transferActivityIcon { color:#0d7479; } QLabel#transferActivityTitle { color:#172630; } QLabel#transferActivityPercent { color:#0a6d72; } QLabel#transferActivityFile { color:#101c25; } QLabel#transferActivityDetail, QLabel#transferActivityDestination { color:#4e6170; }
QPushButton#transferQueueButton { background:#edf4f6; color:#17454a; border:1px solid #aabec5; }
QPushButton#transferQueueButton:hover { background:#deecef; color:#0d3337; }
QLabel#remoteFolderStatus, QLabel#selectionStatus { color:#4d6070; } QLabel#transferSummary { color:#344956; }
QProgressBar#inlineTransferProgress { background:#e4ebef; color:#102126; border:1px solid #aebdc5; } QProgressBar#inlineTransferProgress::chunk { background:#58b7b4; }
QProgressBar#transferProgress { background:#e6edf1; color:#122128; border:1px solid #b1bec6; } QProgressBar#transferProgress::chunk { background:#58b7b4; }
QSplitter#workspaceSplitter::handle, QSplitter::handle { background:#d3dde4; } QSplitter#workspaceSplitter::handle:hover, QSplitter::handle:hover { background:#a8bac5; }
QScrollBar:vertical { background:#eef2f5; width:12px; } QScrollBar::handle:vertical { background:#b2c0ca; min-height:28px; border-radius:5px; } QScrollBar::handle:vertical:hover { background:#91a5b2; }
QScrollBar:horizontal { background:#eef2f5; height:12px; } QScrollBar::handle:horizontal { background:#b2c0ca; min-width:28px; border-radius:5px; } QScrollBar::handle:horizontal:hover { background:#91a5b2; }
QToolTip { background:#fff; color:#111820; border:1px solid #9faeba; }
QFrame#multiExecBanner { background:#fff0f1; border:1px solid #d47b82; }
QLabel#multiExecBannerText { color:#8b1e27; }
QFrame#multiExecTile { background:#fff; border:1px solid #b7c5cf; }
QFrame#multiExecTileHeader { background:#edf3f6; border:none; border-bottom:1px solid #b7c5cf; }
QLabel#multiExecTileTitle { color:#0d676c; }
QCheckBox#multiExecEnabled { color:#1f653c; }
QLabel#multiExecDialogTitle { color:#0c6f74; }

QLabel#authHint { background:#eef5f6; color:#17464b; border:1px solid #b7ced1; }
QLabel#authBadge { color:#16585d; background:#e0f0f1; border:1px solid #aacacc; }
QFrame#disconnectBanner {
    background:#fff0f1; border-top:1px solid #e2a4aa; border-bottom:1px solid #e2a4aa;
}
QLabel#disconnectText { color:#7c222b; }
QPushButton#reconnectButton { background:#e4f5ea; color:#175c38; border:1px solid #8fc2a5; }
QPushButton#disconnectCloseButton { background:#f8e7e7; color:#762a2a; border:1px solid #d5aaaa; }

"""


COFFEE_QSS = r"""
QMainWindow, QDialog, QWidget { background:#f3eadc; color:#382b23; }
QWidget#backdropWidget { background:#eee1cf; }
QWidget#sessionWorkspace, QWidget#sessionFilesPanel, QFrame#terminalContainer,
QTabWidget#mainTabs::pane, QStackedWidget#SftpStack { background:#f7efe3; }
QMenuBar, QToolBar#MainToolbar, QStatusBar { background:#e8d8c2; color:#3d3027; border-color:#c8af90; }
QMenu { background:#f8f0e5; color:#362a22; border:1px solid #bfa787; }
QMenu::item:selected { background:#d9c1a1; color:#2e211a; }
QPushButton, QToolButton { background:#efe1ce; color:#352820; border:1px solid #bda483; }
QPushButton:hover, QToolButton:hover { background:#e3ceb2; border-color:#9e7d58; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background:#fff9f0; color:#32271f; border:1px solid #bda98f;
    selection-background-color:#c9a77f; selection-color:#251b15;
}
QListWidget, QTreeWidget, QTreeView {
    background:#fffaf2; alternate-background-color:#f3e8d7; color:#30251e;
    border:1px solid #c4ad8f; selection-background-color:#d9bd98; selection-color:#2a1f18;
}
QHeaderView::section { background:#e7d6bf; color:#49382c; border:1px solid #c8b091; padding:6px; }
QTabBar::tab { background:#e5d2b8; color:#5a4738; border:1px solid #bfa889; border-bottom:none; }
QTabBar::tab:selected { background:#fff7ec; color:#714c2b; border-top:2px solid #a87342; }
QDockWidget, QDockWidget::title { color:#49392d; background:#e5d3ba; }
QDockWidget#SessionsDock, QDockWidget#SftpDock, QDockWidget#TransferDock { background:#f7efe3; }
QFrame#terminalHeader { background:#e7d6bf; border-bottom:1px solid #c4ab8b; }
QWebEngineView#xtermView { background:#efe2cf; border:none; }
QFrame#homeCard, QFrame#transferActivityCard { background:#fff8ee; border:1px solid #c5ad8d; }
QLabel#brand, QLabel#cardTitle, QLabel#zoomIndicator,
QLabel#transferActivityIcon, QLabel#transferActivityPercent { color:#8b5e34; }
QLabel#homeTitle, QLabel#sessionTitle, QLabel#transferActivityFile,
QLabel#transferActivityTitle { color:#35271f; }
QLabel#muted, QLabel#homeSubtitle, QLabel#remoteFolderStatus,
QLabel#selectionStatus, QLabel#transferActivityDetail,
QLabel#transferActivityDestination, QLabel#transferSummary { color:#705d4c; }
QProgressBar#inlineTransferProgress, QProgressBar#transferProgress { background:#e2d2bd; color:#3a2c22; border:1px solid #bca283; }
QProgressBar#inlineTransferProgress::chunk, QProgressBar#transferProgress::chunk { background:#b88757; }
QFrame#multiExecBanner { background:#f7ded5; border:1px solid #c98770; }
QLabel#multiExecBannerText { color:#7f3825; }
QFrame#multiExecTile { background:#fff8ee; border:1px solid #bda688; }
QFrame#multiExecTileHeader { background:#ead8c0; border:none; border-bottom:1px solid #bda688; }
QLabel#multiExecTileTitle { color:#76502f; }
QCheckBox#multiExecEnabled { color:#4f673b; }
QLabel#authHint { background:#f0e2d0; color:#5c4737; border:1px solid #c6af90; }
QLabel#authBadge { color:#6e4e33; background:#ead5bc; border:1px solid #c2a381; }
QToolTip { background:#fff7eb; color:#34271f; border:1px solid #a98e6d; }
QScrollBar:vertical, QScrollBar:horizontal { background:#eadcc9; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background:#bba386; border-radius:5px; }
"""



ACCENT_COLORS = {
    "cyan": "#2aa6b3",
    "blue": "#3b82f6",
    "green": "#3ca36a",
    "purple": "#9b6bd3",
    "amber": "#d69a35",
    "red": "#d65757",
    "gray": "#788594",
}

THEME_VARIANTS = {
    "midnight": {
        "bg": "#07111f", "panel": "#0a1728", "control": "#102238",
        "hover": "#17304d", "text": "#d8e7f6", "muted": "#8da5bd",
    },
    "graphite": {
        "bg": "#101214", "panel": "#171a1e", "control": "#20242a",
        "hover": "#2b3138", "text": "#e1e4e8", "muted": "#9ba2aa",
    },
    "forest": {
        "bg": "#07130d", "panel": "#0d1c13", "control": "#14281b",
        "hover": "#1d3826", "text": "#d9eadf", "muted": "#91aa99",
    },
    "purple": {
        "bg": "#130b1b", "panel": "#1c1028", "control": "#28183a",
        "hover": "#38204f", "text": "#eadff4", "muted": "#ae99bf",
    },
    "sepia": {
        "bg": "#ead7b8", "panel": "#f3e3c8", "control": "#e0c49a",
        "hover": "#d4b180", "text": "#3b2b20", "muted": "#725b48",
    },
}


def appearance_overlay_qss(mode, accent="cyan", density="normal"):
    accent_value = ACCENT_COLORS.get(accent, ACCENT_COLORS["cyan"])

    if density == "compact":
        pad = 4
        tab_pad = "5px 8px"
        font_size = "10pt"
    elif density == "spacious":
        pad = 8
        tab_pad = "9px 14px"
        font_size = "11pt"
    else:
        pad = 6
        tab_pad = "7px 11px"
        font_size = "10.5pt"

    css = f"""
* {{ font-size: {font_size}; }}
QPushButton, QToolButton {{ padding: {pad}px {pad + 4}px; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ padding: {pad - 1}px; }}
QTabBar::tab {{ padding: {tab_pad}; }}
QListWidget::item {{ padding: {pad + 1}px 5px; }}
QTabBar::tab:selected {{ border-top: 2px solid {accent_value}; }}
QListWidget, QTreeWidget, QTreeView {{
    selection-background-color: {accent_value};
}}
QProgressBar#inlineTransferProgress::chunk,
QProgressBar#transferProgress::chunk {{ background: {accent_value}; }}

QPushButton#LocalShellButton {{
    font-weight: 700;
    border-width: 1px;
}}
QPushButton#LocalShellMenuButton {{
    font-weight: 700;
}}
QLabel#brand, QLabel#cardTitle, QLabel#zoomIndicator,
QLabel#transferActivityIcon, QLabel#transferActivityPercent {{
    color: {accent_value};
}}
"""

    variant = THEME_VARIANTS.get(mode)
    if not variant:
        return css

    bg = variant["bg"]
    panel = variant["panel"]
    control = variant["control"]
    hover = variant["hover"]
    text = variant["text"]
    muted = variant["muted"]

    css += f"""
QMainWindow, QDialog, QWidget {{ background:{bg}; color:{text}; }}
QWidget#backdropWidget,
QWidget#sessionWorkspace,
QWidget#sessionFilesPanel,
QFrame#terminalContainer,
QTabWidget#mainTabs::pane,
QStackedWidget#SftpStack {{ background:{panel}; }}
QMenuBar, QToolBar#MainToolbar, QStatusBar {{
    background:{panel}; color:{text};
}}
QMenu, QFrame#homeCard, QFrame#transferActivityCard {{
    background:{panel}; color:{text};
}}
QPushButton, QToolButton {{
    background:{control}; color:{text};
}}
QPushButton:hover, QToolButton:hover {{
    background:{hover};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit,
QListWidget, QTreeWidget, QTreeView {{
    background:{bg}; color:{text};
}}
QHeaderView::section, QFrame#terminalHeader,
QDockWidget::title {{
    background:{control}; color:{text};
}}
QTabBar::tab {{
    background:{control}; color:{muted};
}}
QTabBar::tab:selected {{
    background:{panel}; color:{text};
}}
QLabel#muted, QLabel#homeSubtitle, QLabel#remoteFolderStatus,
QLabel#selectionStatus, QLabel#transferActivityDetail,
QLabel#transferActivityDestination, QLabel#transferSummary {{
    color:{muted};
}}
"""
    return css


def main():
    global _GUI_DISPATCHER

    app = QApplication(sys.argv)
    ensure_config_dir()
    instance_lock = QLockFile(str(CONFIG_DIR / "mobhector.lock"))
    if not instance_lock.tryLock(100):
        QMessageBox.information(None, "MobHector", "MobHector ya está abierto o su configuración está en uso. Revisa la ventana existente.")
        return
    _GUI_DISPATCHER = GuiDispatcher()

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyle("Fusion")

    app.setPalette(palette_for_mode("dark"))
    app.setStyleSheet(QSS)

    LOGGER.info("Starting %s %s log=%s", APP_NAME, APP_VERSION, LOG_FILE)
    win = MainWindow()
    if not win.isVisible():
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
