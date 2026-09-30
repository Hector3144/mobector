# -*- coding: utf-8 -*-
"""Motor puro de transferencias SFTP para MobHector.

Diseñado para no bloquear el navegador SFTP: si la conexión ofrece
``open_sftp_session()``, cada transferencia usa su propio canal SSH/SFTP.
Los archivos se escriben a nombres temporales y sólo reemplazan el destino
cuando se han cerrado y validado.
"""
from __future__ import annotations

import os
import errno
import posixpath
import stat
import time
import uuid
import re
from pathlib import Path
from contextlib import contextmanager

DEFAULT_CHUNK_SIZE = 512 * 1024
PROGRESS_INTERVAL = 0.10


class TransferCancelled(RuntimeError):
    pass


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise TransferCancelled("Transferencia cancelada por el usuario")


def _validate_chunk_size(value):
    if not isinstance(value, int) or not 4096 <= value <= 4 * 1024 * 1024:
        raise ValueError("Tamaño de bloque fuera de 4 KiB–4 MiB")


def _safe_local_path(root, path):
    root = Path(root).resolve()
    target = Path(path)
    # Reject symlinks/reparse points rather than following existing destination trees.
    current = target
    while current != root and current != current.parent:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError("El destino contiene un enlace o junction")
        current = current.parent
    if not target.resolve().is_relative_to(root):
        raise ValueError("La descarga sale de la carpeta seleccionada")
    return str(target)



def remote_join(base: str, name: str) -> str:
    base = str(base or "/")
    name = str(name or "").lstrip("/")
    return "/" + name if base == "/" else posixpath.join(base, name)


def _is_not_found(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    return getattr(exc, "errno", None) == errno.ENOENT


def _safe_child_name(name: str) -> str:
    """Reject remote-controlled path traversal when writing to Windows."""
    value = str(name or "")
    if (
        not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or any(c in value for c in '<>:"|?*')
        or value.endswith((' ', '.'))
        or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', value, re.I)
    ):
        raise ValueError(
            f"Nombre remoto no seguro para descarga local: {value!r}"
        )
    return value


def _emit(progress, *, stage, detail, done=0, total=0, started_at=None, force_percent=None):
    now = time.monotonic()
    elapsed = max(0.001, now - started_at) if started_at is not None else 0.0
    speed = (done / elapsed) if elapsed > 0 and done > 0 else 0.0
    if force_percent is not None:
        percent = int(force_percent)
    elif total:
        percent = int(done * 100 / total)
    else:
        percent = 0

    # 100% significa: descriptor cerrado + tamaño validado + destino publicado.
    if stage == "transferring":
        percent = min(percent, 99)

    progress({
        "stage": stage,
        "detail": detail,
        "percent": max(0, min(100, int(percent))),
        "bytes_done": int(done),
        "bytes_total": int(total),
        "speed": float(speed),
    })


@contextmanager
def _sftp_session(connection):
    """Canal dedicado cuando es posible; fallback compatible con tests/legacy."""
    connection.ensure()
    opener = getattr(connection, "open_sftp_session", None)
    if callable(opener):
        sftp = opener()
        try:
            if hasattr(sftp, "get_channel"):
                sftp.get_channel().settimeout(30)
            yield sftp
        finally:
            try:
                sftp.close()
            except Exception:
                pass
        return

    # Conexiones fake/legacy usan el canal compartido y su lock.
    lock = getattr(connection, "lock", None)
    if lock is None:
        yield connection.sftp
    else:
        with lock:
            yield connection.sftp


def _remote_exists(sftp, path):
    try:
        sftp.lstat(path)
        return True
    except (IOError, OSError) as exc:
        if _is_not_found(exc):
            return False
        raise


def _publish_remote(sftp, temp_path, final_path):
    """Publica un archivo temporal sin convertir directorios en archivos.

    Seguridad: si ``final_path`` ya es un directorio, se aborta. Un upload
    de archivo nunca debe renombrar/ocultar un árbol remoto completo sólo
    porque el nombre del archivo coincide con una carpeta existente.
    """
    try:
        existing = sftp.lstat(final_path)
    except (IOError, OSError) as exc:
        if _is_not_found(exc):
            existing = None
        else:
            raise

    if existing is not None and stat.S_ISDIR(existing.st_mode):
        raise IsADirectoryError(
            f"El destino remoto es un directorio y no puede reemplazarse "
            f"por un archivo: {final_path}"
        )

    posix_rename = getattr(sftp, "posix_rename", None)
    if callable(posix_rename):
        try:
            posix_rename(temp_path, final_path)
            return
        except Exception:
            # Algunos servidores no implementan realmente la extensión.
            pass

    if not _remote_exists(sftp, final_path):
        sftp.rename(temp_path, final_path)
        return

    # Fallback transaccional: conservar el destino antiguo hasta que el
    # temporal haya sido publicado. Si falla, se restaura el original.
    backup_path = final_path + f".mobhector-backup-{uuid.uuid4().hex}"
    sftp.rename(final_path, backup_path)
    try:
        sftp.rename(temp_path, final_path)
    except Exception:
        try:
            if _remote_exists(sftp, final_path):
                sftp.remove(final_path)
        except Exception:
            pass
        try:
            sftp.rename(backup_path, final_path)
        except Exception:
            pass
        raise
    else:
        try:
            sftp.remove(backup_path)
        except Exception:
            # El archivo nuevo ya quedó publicado; la copia de seguridad
            # sobrante es preferible a perder datos.
            pass


def upload(connection, paths, remote_base, progress, chunk_size=DEFAULT_CHUNK_SIZE, cancel=None):
    """Sube archivos/carpetas con canal dedicado, temp remoto y progreso real."""
    _validate_chunk_size(chunk_size)
    _check_cancel(cancel)
    if any(not os.path.exists(p) for p in paths):
        raise FileNotFoundError("Una ruta seleccionada ya no existe")
    paths = [os.path.abspath(p) for p in paths]
    if not paths:
        raise ValueError("No hay rutas locales válidas para subir.")

    progress({"stage": "preparing", "detail": "Analizando archivos locales…", "percent": 0})

    jobs = []
    total = 0
    for src in paths:
        _check_cancel(cancel)
        if os.path.islink(src):
            raise ValueError("Selecciona el archivo original, no un enlace simbólico")
        if os.path.isdir(src):
            root_name = os.path.basename(src.rstrip("\\/"))
            for root, _dirs, files in os.walk(src):
                _check_cancel(cancel)
                if any(os.path.islink(os.path.join(root, n)) for n in _dirs + files):
                    raise ValueError("La carpeta contiene enlaces simbólicos; selecciona los originales")
                rel = os.path.relpath(root, src)
                rdir = remote_join(remote_base, root_name)
                if rel != ".":
                    rdir = remote_join(rdir, rel.replace("\\", "/"))
                jobs.append(("DIR", rdir, 0))
                for name in files:
                    lp = os.path.join(root, name)
                    rp = remote_join(rdir, name)
                    if not os.path.isfile(lp):
                        raise ValueError("La carpeta contiene un dispositivo o archivo especial")
                    size = os.path.getsize(lp)
                    total += size
                    jobs.append((lp, rp, size))
        else:
            if not os.path.isfile(src):
                raise ValueError("Sólo se admiten archivos regulares y carpetas")
            size = os.path.getsize(src)
            total += size
            jobs.append((src, remote_join(remote_base, os.path.basename(src)), size))

    started = time.monotonic()
    sent = 0
    last_report = 0.0
    created = set()
    label = os.path.basename(paths[0].rstrip("\\/")) if len(paths) == 1 else f"{len(paths)} elementos"
    _emit(progress, stage="transferring", detail=label, done=0, total=total, started_at=started, force_percent=0)

    def report(current, detail, force=False):
        nonlocal last_report
        now = time.monotonic()
        if force or (now - last_report) >= PROGRESS_INTERVAL:
            last_report = now
            _emit(progress, stage="transferring", detail=detail, done=current, total=total, started_at=started)

    with _sftp_session(connection) as sftp:
        def mkdir_p(rdir):
            if not rdir or rdir == "/" or rdir in created:
                return
            parts = []
            cur = rdir
            while cur and cur != "/":
                parts.append(cur)
                cur = posixpath.dirname(cur)
            for p in reversed(parts):
                if p in created:
                    continue
                try:
                    a = sftp.stat(p)
                    if not stat.S_ISDIR(a.st_mode):
                        raise RuntimeError(
                            f"La ruta remota existe y no es directorio: {p}"
                        )
                except (IOError, OSError) as exc:
                    if not _is_not_found(exc):
                        raise
                    try:
                        sftp.mkdir(p)
                    except (IOError, OSError) as mkdir_exc:
                        # Carrera benigna: otro proceso pudo crearla.
                        try:
                            a = sftp.stat(p)
                        except Exception:
                            raise mkdir_exc
                        if not stat.S_ISDIR(a.st_mode):
                            raise RuntimeError(
                                f"La ruta remota existe y no es directorio: {p}"
                            )
                created.add(p)

        for local_file, remote_file, expected_size in jobs:
            _check_cancel(cancel)
            if local_file == "DIR":
                mkdir_p(remote_file)
                continue

            mkdir_p(posixpath.dirname(remote_file))
            current_name = os.path.basename(local_file)
            temp_remote = (
                remote_file
                + f".mobhector-part-{uuid.uuid4().hex}"
            )

            try:
                with open(local_file, "rb", buffering=chunk_size) as local_f:
                    remote_f = sftp.open(temp_remote, "wx")
                    try:
                        try:
                            remote_f.set_pipelined(True)
                        except Exception:
                            pass
                        while True:
                            _check_cancel(cancel)
                            chunk = local_f.read(chunk_size)
                            if not chunk:
                                break
                            remote_f.write(chunk)
                            sent += len(chunk)
                            report(sent, current_name)
                        try:
                            remote_f.flush()
                        except Exception:
                            pass
                    finally:
                        remote_f.close()

                actual = int(sftp.stat(temp_remote).st_size or 0)
                if actual != int(expected_size):
                    raise RuntimeError(
                        f"Tamaño remoto inválido para {remote_file}: "
                        f"esperado={expected_size}, escrito={actual}"
                    )

                _check_cancel(cancel)
                _publish_remote(sftp, temp_remote, remote_file)
                report(sent, current_name, force=True)

            except Exception:
                try:
                    if _remote_exists(sftp, temp_remote):
                        sftp.remove(temp_remote)
                except Exception:
                    pass
                raise

    elapsed = max(0.001, time.monotonic() - started)
    progress({
        "stage": "complete",
        "detail": label,
        "percent": 100,
        "bytes_done": total,
        "bytes_total": total,
        "speed": (total / elapsed) if total else 0.0,
    })
    return {"count": len(paths), "bytes": total, "elapsed": elapsed}


def download(connection, rows, dest, progress, chunk_size=DEFAULT_CHUNK_SIZE, cancel=None):
    """Descarga con canal dedicado y archivos .part locales publicados con os.replace."""
    _validate_chunk_size(chunk_size)
    _check_cancel(cancel)
    dest = os.path.realpath(dest)
    if not rows:
        raise ValueError("No hay elementos remotos para descargar.")
    os.makedirs(dest, exist_ok=True)
    progress({"stage": "preparing", "detail": "Calculando tamaño remoto…", "percent": 0})

    with _sftp_session(connection) as sftp:
        planned_names = set()
        def size_remote(path, relative):
            _check_cancel(cancel)
            folded = relative.casefold()
            if folded in planned_names:
                raise ValueError("Dos nombres remotos coinciden en Windows: " + relative)
            planned_names.add(folded)
            a = sftp.lstat(path)
            if stat.S_ISDIR(a.st_mode):
                total_size = 0
                for child in sftp.listdir_attr(path):
                    if child.filename in (".", ".."):
                        continue
                    child_name = _safe_child_name(child.filename)
                    total_size += size_remote(
                        remote_join(path, child_name), posixpath.join(relative, child_name)
                    )
                return total_size
            return int(a.st_size or 0) if stat.S_ISREG(a.st_mode) else 0

        total = sum(size_remote(r["path"], _safe_child_name(posixpath.basename(r["path"]))) for r in rows)
        started = time.monotonic()
        done = 0
        last_report = 0.0
        label = posixpath.basename(rows[0]["path"]) if len(rows) == 1 else f"{len(rows)} elementos"
        _emit(progress, stage="transferring", detail=label, done=0, total=total, started_at=started, force_percent=0)

        def report(current, detail, force=False):
            nonlocal last_report
            now = time.monotonic()
            if force or (now - last_report) >= PROGRESS_INTERVAL:
                last_report = now
                _emit(progress, stage="transferring", detail=detail, done=current, total=total, started_at=started)

        def get_one(remote_path, local_path):
            nonlocal done
            _check_cancel(cancel)
            local_path = _safe_local_path(dest, local_path)
            a = sftp.lstat(remote_path)
            if stat.S_ISDIR(a.st_mode):
                os.makedirs(local_path, exist_ok=True)
                for child in sftp.listdir_attr(remote_path):
                    if child.filename in (".", ".."):
                        continue
                    child_name = _safe_child_name(child.filename)
                    get_one(
                        remote_join(remote_path, child_name),
                        os.path.join(local_path, child_name),
                    )
                return
            if not stat.S_ISREG(a.st_mode):
                return

            parent = os.path.dirname(local_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            temp_local = local_path + f".mobhector-part-{uuid.uuid4().hex}"
            expected = int(a.st_size or 0)
            try:
                remote_f = sftp.open(remote_path, "rb")
                try:
                    prefetch = getattr(remote_f, "prefetch", None)
                    if callable(prefetch) and expected:
                        prefetch(file_size=expected, max_concurrent_requests=32)
                    with open(temp_local, "xb", buffering=chunk_size) as local_f:
                        while True:
                            _check_cancel(cancel)
                            chunk = remote_f.read(chunk_size)
                            if not chunk:
                                break
                            local_f.write(chunk)
                            done += len(chunk)
                            report(done, posixpath.basename(remote_path))
                        local_f.flush()
                        try:
                            os.fsync(local_f.fileno())
                        except OSError:
                            pass
                finally:
                    remote_f.close()

                actual = os.path.getsize(temp_local)
                if actual != expected:
                    raise RuntimeError(
                        f"Tamaño descargado inválido para {remote_path}: "
                        f"local={actual}, remoto={expected}"
                    )

                _check_cancel(cancel)
                _safe_local_path(dest, local_path)
                os.replace(temp_local, local_path)
                try:
                    os.utime(local_path, (a.st_mtime, a.st_mtime))
                except Exception:
                    pass
                report(done, posixpath.basename(remote_path), force=True)

            except Exception:
                try:
                    os.remove(temp_local)
                except OSError:
                    pass
                raise

        for row in rows:
            base_name = _safe_child_name(
                posixpath.basename(row["path"])
            )
            get_one(
                row["path"],
                os.path.join(dest, base_name),
            )

    elapsed = max(0.001, time.monotonic() - started)
    progress({
        "stage": "complete",
        "detail": label,
        "percent": 100,
        "bytes_done": total,
        "bytes_total": total,
        "speed": (total / elapsed) if total else 0.0,
    })
    return {"count": len(rows), "bytes": total, "elapsed": elapsed}
