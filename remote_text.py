"""Lossless UTF-8 editor decoding; reject binary, invalid or mixed newline files."""
import hashlib

MAX_EDITOR_BYTES = 3 * 1024 * 1024


def decode_document(raw):
    if len(raw) > MAX_EDITOR_BYTES:
        raise ValueError('Archivo demasiado grande para el editor (>3 MiB)')
    decoded = raw.decode('utf-8-sig', errors='strict')
    if '\x00' in decoded:
        raise ValueError('Archivo binario; usa SFTP')
    crlf = '\r\n' in decoded
    rest = decoded.replace('\r\n', '')
    lf, cr = '\n' in rest, '\r' in rest
    if sum((crlf, lf, cr)) > 1:
        raise ValueError('Saltos de línea mezclados; descarga el archivo para editarlo sin normalización')
    newline = '\r\n' if crlf else ('\r' if cr else '\n')
    normalized = decoded.replace('\r\n','\n').replace('\r','\n')
    return normalized, hashlib.sha256(raw).hexdigest(), newline, raw.startswith(b'\xef\xbb\xbf')


def encode_document(text, newline, bom):
    raw = text.replace('\n', newline).encode('utf-8')
    return (b'\xef\xbb\xbf' if bom else b'') + raw
