"""Validate portable sessions without trusting executable imported fields."""
import ipaddress
import json
import re
import uuid
from pathlib import Path

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_SESSIONS = 2000


def text(value, name, limit=1024):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f'{name}: texto inválido o demasiado largo')
    return value.strip()


def validate_session(raw):
    if not isinstance(raw, dict):
        raise ValueError('Cada sesión debe ser un objeto JSON')
    host = text(raw.get('host', ''), 'Host', 253)
    if not host or host.startswith('-'):
        raise ValueError('Host vacío o inválido')
    if host.startswith('[') or host.endswith(']'):
        if not (host.startswith('[') and host.endswith(']')):
            raise ValueError('Dirección IP entre corchetes incompleta')
        host = host[1:-1]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?\.?', host):
            raise ValueError('Host inválido; introduce un nombre DNS o una IP')
    user = text(raw.get('username', ''), 'Usuario', 256)
    if not user or user.startswith('-') or any(c.isspace() for c in user):
        raise ValueError('Usuario inválido')
    port = raw.get('port', 22)
    if isinstance(port, bool) or not isinstance(port, (str, int)):
        raise ValueError('Puerto inválido')
    try:
        port = int(port)
    except ValueError:
        raise ValueError('Puerto inválido') from None
    if not 1 <= port <= 65535:
        raise ValueError('Puerto fuera de 1–65535')
    mode = raw.get('auth_mode', 'key')
    if mode not in ('key', 'password'):
        raise ValueError('Método de autenticación no portable')
    session = dict(host=host, username=user, port=port, auth_mode=mode,
                   remember_password=False, credential_id=uuid.uuid4().hex)
    for key in ('name', 'folder', 'key_file', 'remote_home', 'remote_inbox'):
        session[key] = text(raw.get(key, ''), key, 4096 if key != 'name' else 256)
    if type(raw.get('favorite', False)) is not bool:
        raise ValueError('favorite debe ser true o false')
    session['favorite'] = raw.get('favorite', False)
    # Imported startup commands never execute merely by connecting.
    session['startup_command'] = ''
    session['x11_enabled'] = False  # Imported sessions cannot grant display access.
    return session


def read_sessions(path, existing=()):
    path = Path(path)
    with path.open('rb') as handle:
        raw_bytes = handle.read(MAX_IMPORT_BYTES + 1)
    if len(raw_bytes) > MAX_IMPORT_BYTES:
        raise ValueError('Importación limitada a 2 MiB')
    payload = json.loads(raw_bytes.decode('utf-8-sig'))
    if not isinstance(payload, dict) or not isinstance(payload.get('sessions'), list):
        raise ValueError('Se requiere un objeto con una lista sessions')
    rows = payload['sessions']
    if len(rows) > MAX_SESSIONS or len(existing) + len(rows) > MAX_SESSIONS:
        raise ValueError('Límite de 2000 sesiones')
    def identity(s):
        return (str(s.get('host', '')).casefold(), str(s.get('port', 22)),
                s.get('username'), s.get('name', ''))
    seen = {identity(s) for s in existing}
    result = []
    skipped = 0
    for index, raw in enumerate(rows, 1):
        try:
            session = validate_session(raw)
        except ValueError as exc:
            raise ValueError(f'Sesión {index}: {exc}') from exc
        key = identity(session)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        result.append(session)
    return result, skipped
