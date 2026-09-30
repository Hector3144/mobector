# -*- coding: utf-8 -*-
"""Host-key trust store for MobHector.

Implements explicit trust-on-first-use (TOFU) instead of Paramiko AutoAddPolicy.
Unknown keys are surfaced to the UI so the user can inspect the SHA256
fingerprint before trusting them. Trusted keys are stored in MobHector's own
known_hosts file.
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading
import tempfile
from pathlib import Path

import paramiko
from paramiko.hostkeys import HostKeyEntry


_STORE_LOCK = threading.RLock()


class UnknownHostKeyError(paramiko.SSHException):
    def __init__(self, hostname: str, key: paramiko.PKey):
        self.hostname = str(hostname)
        self.key_type = key.get_name()
        self.key_base64 = key.get_base64()
        self.fingerprint = fingerprint_sha256(key)
        super().__init__(
            "HOST_KEY_UNKNOWN|"
            f"{self.hostname}|{self.key_type}|{self.key_base64}|{self.fingerprint}"
        )


class PromptHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Never accepts an unknown key silently."""

    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKeyError(hostname, key)


def fingerprint_sha256(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return "SHA256:" + encoded


def configure_client(client: paramiko.SSHClient, known_hosts_file: Path) -> None:
    """Load system + application known hosts and require explicit trust."""
    try:
        client.load_system_host_keys()
    except Exception:
        # A missing/unreadable system known_hosts should not make the app unusable.
        pass

    known_hosts_file = Path(known_hosts_file)
    if known_hosts_file.exists():
        client.load_host_keys(str(known_hosts_file))

    client.set_missing_host_key_policy(PromptHostKeyPolicy())


def parse_unknown_marker(text: str):
    marker = "HOST_KEY_UNKNOWN|"
    pos = str(text).find(marker)
    if pos < 0:
        return None
    payload = str(text)[pos:].splitlines()[0].strip()
    parts = payload.split("|", 4)
    if len(parts) != 5:
        return None
    _, hostname, key_type, key_b64, fingerprint = parts
    return {
        "hostname": hostname,
        "key_type": key_type,
        "key_base64": key_b64,
        "fingerprint": fingerprint,
    }


def parse_mismatch_marker(text: str):
    marker = "HOST_KEY_MISMATCH|"
    pos = str(text).find(marker)
    if pos < 0:
        return None
    payload = str(text)[pos:].splitlines()[0].strip()
    parts = payload.split("|", 6)
    if len(parts) != 7:
        return None
    _, hostname, expected_type, expected_b64, expected_fp, got_type, got_data = parts
    got_b64, got_fp = got_data.rsplit("|", 1) if "|" in got_data else (got_data, "")
    return {
        "hostname": hostname,
        "expected_type": expected_type,
        "expected_base64": expected_b64,
        "expected_fingerprint": expected_fp,
        "got_type": got_type,
        "got_base64": got_b64,
        "got_fingerprint": got_fp,
    }


def mismatch_marker(exc: paramiko.BadHostKeyException) -> str:
    expected = exc.expected_key
    got = exc.key
    return (
        "HOST_KEY_MISMATCH|"
        f"{exc.hostname}|{expected.get_name()}|{expected.get_base64()}|"
        f"{fingerprint_sha256(expected)}|{got.get_name()}|{got.get_base64()}|"
        f"{fingerprint_sha256(got)}"
    )


def _load_store(path: Path) -> paramiko.HostKeys:
    store = paramiko.HostKeys()
    path = Path(path)
    if path.exists():
        store.load(str(path))
    return store


def trust_host_key(
    path: Path,
    hostname: str,
    key_type: str,
    key_base64: str,
) -> None:
    """Add/replace one application-owned trusted host key atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not hostname or any(c.isspace() or c in ',|' for c in hostname):
        raise ValueError("Nombre de host inválido")
    if any(c.isspace() for c in key_type + key_base64):
        raise ValueError("Formato de clave inválido")
    entry = HostKeyEntry.from_line(
        f"{hostname} {key_type} {key_base64}"
    )
    if entry is None or entry.key is None:
        raise ValueError("La clave SSH recibida no tiene un formato válido.")

    # Dos conexiones desconocidas pueden ser aceptadas casi a la vez.
    # Serializar load/add/save evita que la última sobrescriba la primera.
    with _STORE_LOCK:
        store = _load_store(path)
        store.add(hostname, key_type, entry.key)

        fd, tmp_name = tempfile.mkstemp(
            prefix="known-hosts-",
            suffix=".tmp",
            dir=str(path.parent),
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            store.save(str(tmp))
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def remove_host(path: Path, hostname: str) -> bool:
    path = Path(path)
    with _STORE_LOCK:
        if not path.exists():
            return False
        store = _load_store(path)
        if hostname not in store:
            return False
        del store[hostname]
        fd, tmp_name = tempfile.mkstemp(
            prefix="known-hosts-",
            suffix=".tmp",
            dir=str(path.parent),
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            store.save(str(tmp))
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        return True

