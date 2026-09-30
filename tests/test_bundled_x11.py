import hashlib
from pathlib import Path
import tempfile
import unittest
from x11_forwarding import find_windows_executable
from install_support import apply_update, REQUIRED


class BundledX11Tests(unittest.TestCase):
    def test_bundled_server_preferred_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'vendor/vcxsrv/vcxsrv.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'MZ')
            self.assertEqual(find_windows_executable({}, root), exe.resolve())
            external = root / 'external/vcxsrv.exe'
            external.parent.mkdir()
            external.write_bytes(b'MZ')
            self.assertEqual(find_windows_executable({'x11_executable': str(external)}, root), external.resolve())
            with self.assertRaises(ValueError):
                find_windows_executable({'x11_executable': str(root/'missing.exe')}, root)

    def test_update_copies_and_rolls_back_vendor_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); src = root/'src'; dst = root/'dst'
            names = REQUIRED | {'vendor/vcxsrv/vcxsrv.exe', 'vendor/vcxsrv/xkb/test'}
            for name in names:
                p=src/name;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(b'new')
            (src/'MANIFEST_SHA256.txt').write_text(''.join(
                hashlib.sha256((src/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in sorted(names)))
            old=dst/'vendor/vcxsrv/vcxsrv.exe';old.parent.mkdir(parents=True);old.write_bytes(b'old')
            def fail(_):raise RuntimeError('failed validation')
            with self.assertRaises(RuntimeError):apply_update(src,dst,root/'backups',validate=fail)
            self.assertEqual(old.read_bytes(),b'old')
            self.assertFalse((dst/'vendor/vcxsrv/xkb/test').exists())
            apply_update(src,dst,root/'backups')
            self.assertEqual(old.read_bytes(),b'new')
            self.assertEqual((dst/'vendor/vcxsrv/xkb/test').read_bytes(),b'new')
