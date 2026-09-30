# -*- coding: utf-8 -*-
"""
MobHector - almacenamiento de contraseñas SSH en Windows Credential Manager.

Nunca escribe la contraseña en config.json. Para credenciales genéricas:
- CRED_TYPE_GENERIC
- CRED_PERSIST_LOCAL_MACHINE
- ámbito del usuario de Windows que ejecuta MobHector

En sistemas no Windows las funciones fallan de forma segura / devuelven False.
"""
from __future__ import annotations

import os
import ctypes
import uuid
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

_TARGET_PREFIX = "MobHector:SSH:"
_LEGACY_TARGET_PREFIX = "RusterFilesPro:SSH:"


class CredentialStoreError(RuntimeError):
    pass


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


LPBYTE = ctypes.POINTER(ctypes.c_ubyte)


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", LPBYTE),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


_advapi = None


def new_credential_id() -> str:
    return uuid.uuid4().hex


def target_for(session: dict, *, legacy=False) -> str:
    credential_id = str(session.get("credential_id") or "").strip()
    if not credential_id:
        raise CredentialStoreError(
            "La sesión no tiene credential_id."
        )
    prefix = _LEGACY_TARGET_PREFIX if legacy else _TARGET_PREFIX
    return prefix + credential_id


def is_available() -> bool:
    return os.name == "nt" and hasattr(ctypes, "WinDLL")


def _api():
    global _advapi

    if not is_available():
        raise CredentialStoreError(
            "Windows Credential Manager no está disponible."
        )

    if _advapi is not None:
        return _advapi

    advapi = ctypes.WinDLL(
        "Advapi32.dll",
        use_last_error=True
    )

    advapi.CredWriteW.argtypes = [
        ctypes.POINTER(CREDENTIALW),
        wintypes.DWORD,
    ]
    advapi.CredWriteW.restype = wintypes.BOOL

    advapi.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(PCREDENTIALW),
    ]
    advapi.CredReadW.restype = wintypes.BOOL

    advapi.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi.CredDeleteW.restype = wintypes.BOOL

    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None

    _advapi = advapi
    return advapi


def _raise_last_error(action: str):
    error = ctypes.get_last_error()
    raise CredentialStoreError(
        f"{action} falló en Windows Credential Manager "
        f"(WinError {error}: {ctypes.FormatError(error).strip()})."
    )


def write_password(session: dict, password: str) -> None:
    if password is None:
        raise CredentialStoreError(
            "No se recibió una contraseña para guardar."
        )

    password = str(password)
    blob = password.encode("utf-16-le")

    # Mantener el buffer vivo hasta que CredWriteW retorne.
    if blob:
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        blob_ptr = ctypes.cast(buffer, LPBYTE)
    else:
        buffer = None
        blob_ptr = None

    target = target_for(session)
    username = str(session.get("username") or "")
    host = str(session.get("host") or "")
    port = int(session.get("port", 22))

    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = (
        f"MobHector SSH - {username}@{host}:{port}"
    )
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = blob_ptr
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = username

    api = _api()
    ctypes.set_last_error(0)

    try:
        if not api.CredWriteW(ctypes.byref(cred), 0):
            _raise_last_error("Guardar credencial")
    finally:
        if buffer is not None:
            ctypes.memset(ctypes.addressof(buffer), 0, len(blob))

    # No retornar / registrar la contraseña.
    del buffer
    del blob


def _read_target(target: str):
    api = _api()
    cred_ptr = PCREDENTIALW()
    ctypes.set_last_error(0)

    if not api.CredReadW(
        target,
        CRED_TYPE_GENERIC,
        0,
        ctypes.byref(cred_ptr),
    ):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        _raise_last_error("Leer credencial")

    try:
        cred = cred_ptr.contents
        size = int(cred.CredentialBlobSize)
        if size <= 0:
            return ""
        raw = ctypes.string_at(cred.CredentialBlob, size)
        return raw.decode("utf-16-le")
    finally:
        api.CredFree(cred_ptr)


def read_password(session: dict):
    """Devuelve str o None y migra credenciales RusterFiles legacy."""
    value = _read_target(target_for(session))
    if value is not None:
        return value

    # Compatibilidad transparente con credenciales creadas por RusterFiles.
    legacy_value = _read_target(target_for(session, legacy=True))
    if legacy_value is None:
        return None

    try:
        write_password(session, legacy_value)
        _delete_target(target_for(session, legacy=True))
    except Exception:
        # Leer sigue siendo más importante que completar la migración.
        pass
    return legacy_value


def _delete_target(target: str) -> bool:
    api = _api()
    ctypes.set_last_error(0)
    if not api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return False
        _raise_last_error("Eliminar credencial")
    return True


def delete_password(session: dict) -> bool:
    """Elimina credencial MobHector y cualquier entrada legacy equivalente."""
    credential_id = str(session.get("credential_id") or "").strip()
    if not credential_id:
        return False

    deleted = _delete_target(target_for(session))
    legacy_deleted = _delete_target(target_for(session, legacy=True))
    return bool(deleted or legacy_deleted)


def has_password(session: dict) -> bool:
    if not is_available():
        return False

    try:
        value = read_password(session)
        return value is not None
    except CredentialStoreError:
        return False
