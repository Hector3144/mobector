import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transfer_engine import upload, download, _safe_child_name, TransferCancelled
from terminal_io import AsyncChannelWriter
from session_validation import read_sessions, validate_session
from install_support import apply_update, verify_package, REQUIRED
from validar_transferencias import Conn


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_windows_names(self):
        for name in ('..', '../a', 'C:foo', 'x:y', 'CON', 'NUL.txt', 'com1.txt',
                     'LPT²', 'a.', 'a ', 'x/y', 'x\\y', 'a\x00b', 'x?y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _safe_child_name(name)
        self.assertEqual(_safe_child_name('Informe ñ.txt'), 'Informe ñ.txt')

    def test_import_rejects_all_before_mutation(self):
        existing = [{'host': 'example.org', 'username': 'user'}]
        p = self.root/'sessions.json'
        p.write_text(json.dumps({'sessions': [dict(host='host', username='u'), dict(host='-oProxyCommand=x', username='u')]}))
        with self.assertRaises(ValueError): read_sessions(p, existing)
        self.assertEqual(len(existing), 1)

    def test_import_strips_secrets_and_commands_and_deduplicates(self):
        raw = dict(host='host', username='u', auth_mode='password', port='22',
                   startup_command='danger', password='secret', credential_id='victim', remember_password=True)
        p = self.root/'sessions.json'; p.write_text(json.dumps({'sessions': [raw, raw]}))
        rows, skipped = read_sessions(p)
        self.assertEqual((len(rows), skipped), (1, 1))
        self.assertEqual(rows[0]['startup_command'], '')
        self.assertNotIn('password', rows[0]); self.assertFalse(rows[0]['remember_password'])
        self.assertNotEqual(rows[0]['credential_id'], 'victim')

    def test_import_invalid_types_ports(self):
        for value in (True, 0, 65536, {}, 22.5, 'a'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_session(dict(host='host', username='u', port=value))
        with self.assertRaises(ValueError): validate_session(dict(host='host', username='u', favorite='false'))

    def test_import_bounded(self):
        p = self.root/'big.json'; p.write_bytes(b' '*(2*1024*1024+1))
        with self.assertRaises(ValueError): read_sessions(p)

    def test_cancel_upload_preserves_destination(self):
        remote=self.root/'remote'; remote.mkdir(); (remote/'file.bin').write_bytes(b'original')
        local=self.root/'local'; local.mkdir(); (local/'file.bin').write_bytes(b'x'*100000)
        event=threading.Event()
        def progress(p):
            if p.get('bytes_done', 0)>0: event.set()
        with self.assertRaises(TransferCancelled):
            upload(Conn(remote), [str(local/'file.bin')], '/', progress, chunk_size=4096, cancel=event)
        self.assertEqual((remote/'file.bin').read_bytes(), b'original')
        self.assertEqual([p.name for p in remote.iterdir()], ['file.bin'])

    def test_cancel_download_preserves_destination(self):
        remote=self.root/'remote'; remote.mkdir(); (remote/'file.bin').write_bytes(b'x'*100000)
        local=self.root/'local'; local.mkdir(); (local/'file.bin').write_bytes(b'original')
        event=threading.Event()
        def progress(p):
            if p.get('bytes_done', 0)>0: event.set()
        with self.assertRaises(TransferCancelled):
            download(Conn(remote), [{'path':'/file.bin'}], str(local), progress, chunk_size=4096, cancel=event)
        self.assertEqual((local/'file.bin').read_bytes(), b'original')
        self.assertEqual([p.name for p in local.iterdir()], ['file.bin'])

    def test_download_cannot_follow_existing_symlink(self):
        if os.name == 'nt': self.skipTest('Symlinks require Windows privilege; covered on Linux')
        remote=self.root/'remote'; (remote/'folder').mkdir(parents=True); (remote/'folder'/'f').write_text('x')
        local=self.root/'local'; local.mkdir(); outside=self.root/'outside'; outside.mkdir()
        (local/'folder').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            download(Conn(remote), [{'path':'/folder'}], str(local), lambda p:None)
        self.assertEqual(list(outside.iterdir()), [])

    def test_cancel_before_start_has_no_side_effects(self):
        event=threading.Event(); event.set()
        with self.assertRaises(TransferCancelled): download(None, [], str(self.root/'missing'), lambda p:None, cancel=event)
        self.assertFalse((self.root/'missing').exists())

    def test_writer_nonblocking_order_and_bound(self):
        entered=threading.Event(); release=threading.Event(); complete=threading.Event()
        class Channel:
            closed=False
            def __init__(self): self.data=[]
            def sendall(self,data):
                entered.set(); release.wait(2); self.data.append(data)
                if len(self.data)==2: complete.set()
        ch=Channel(); errors=[]; writer=AsyncChannelWriter(ch, errors.append, max_bytes=8)
        try:
            start=time.monotonic(); self.assertTrue(writer.submit(b'first'))
            self.assertLess(time.monotonic()-start, .1)
            self.assertTrue(entered.wait(1)); self.assertFalse(writer.submit(b'long'))
            self.assertTrue(writer.submit(b'2'))
            release.set(); self.assertTrue(complete.wait(2)); self.assertEqual(ch.data,[b'first',b'2'])
            self.assertEqual(errors,[])
        finally: release.set(); writer.stop(); writer.thread.join(2)

    def test_writer_partial_send_and_timeout_no_duplicate(self):
        import socket
        complete=threading.Event()
        class Channel:
            closed=False
            def __init__(self):self.data=b'';self.calls=0
            def send(self,data):
                self.calls+=1
                if self.calls==2:raise socket.timeout()
                self.data+=data[:2]
                if self.data==b'abcdef':complete.set()
                return len(data[:2])
        channel=Channel();errors=[];writer=AsyncChannelWriter(channel,errors.append)
        try:
            writer.submit(b'abcdef')
            self.assertTrue(complete.wait(2));self.assertEqual(channel.data,b'abcdef');self.assertEqual(errors,[])
        finally:writer.stop();writer.thread.join(2)

    def test_writer_error_and_stop(self):
        failed=threading.Event()
        class Channel:
            closed=False
            def sendall(self,data): raise OSError('closed')
        writer=AsyncChannelWriter(Channel(), lambda e:failed.set())
        self.assertTrue(writer.submit(b'x')); self.assertTrue(failed.wait(2))
        writer.thread.join(2); self.assertFalse(writer.submit(b'y'))

    def test_editor_lossless_utf8_bom_newlines(self):
        from remote_text import decode_document, encode_document
        for raw in (b'abc\r\ndef\r\n', b'abc\ndef', b'abc\rdef', b'\xef\xbb\xbfa\r\n', 'Español ñ'.encode()):
            text, digest, newline, bom = decode_document(raw)
            self.assertEqual(encode_document(text,newline,bom), raw)
            self.assertEqual(digest,hashlib.sha256(raw).hexdigest())

    def test_editor_rejects_invalid_binary_mixed(self):
        from remote_text import decode_document
        for raw in (b'\xff', b'a\x00b', b'a\r\nb\n', b'a'*(3*1024*1024+1)):
            with self.assertRaises(ValueError):decode_document(raw)

    def test_windows_case_collision_rejected_before_write(self):
        if os.name == 'nt': self.skipTest('Case-sensitive remote fixture exercised on Linux')
        remote=self.root/'remote';remote.mkdir()
        (remote/'A').write_text('one');(remote/'a').write_text('two')
        dest=self.root/'download'
        with self.assertRaises(ValueError):
            download(Conn(remote),[{'path':'/A'},{'path':'/a'}],str(dest),lambda p:None)
        self.assertEqual(list(dest.iterdir()),[])

    def package(self):
        source=self.root/'source'; source.mkdir()
        for rel in REQUIRED:
            path=source/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('new')
        manifest=''.join(hashlib.sha256((source/p).read_bytes()).hexdigest()+'  '+p+'\n' for p in sorted(REQUIRED))
        (source/'MANIFEST_SHA256.txt').write_text(manifest)
        return source

    def test_update_rollback_restores_old_and_removes_new(self):
        source=self.package(); dest=self.root/'dest';dest.mkdir()
        (dest/'mobhector.pyw').write_text('old');(dest/'config.json').write_text('keep')
        def fail(_): raise RuntimeError('injected verification failure')
        with self.assertRaises(RuntimeError): apply_update(source,dest,self.root/'backup',validate=fail)
        self.assertEqual((dest/'mobhector.pyw').read_text(),'old')
        self.assertEqual((dest/'config.json').read_text(),'keep')
        self.assertFalse((dest/'terminal_io.py').exists())

    def test_update_success_and_hash_rejection(self):
        source=self.package();dest=self.root/'dest'
        apply_update(source,dest,self.root/'backups')
        self.assertEqual((dest/'mobhector.pyw').read_text(),'new')
        (source/'mobhector.pyw').write_text('tampered')
        with self.assertRaises(ValueError): verify_package(source)

    def test_manifest_traversal_duplicate_missing(self):
        source=self.package();manifest=source/'MANIFEST_SHA256.txt';original=manifest.read_text()
        for bad in ('../x','C:/x','a\\b','config.json'):
            manifest.write_text(original+'0'*64+'  '+bad+'\n')
            with self.subTest(path=bad), self.assertRaises(ValueError):verify_package(source)
        manifest.write_text(original+original)
        with self.assertRaises(ValueError):verify_package(source)
        manifest.write_text('')
        with self.assertRaises(ValueError):verify_package(source)

    def test_host_key_tofu_and_injection(self):
        import paramiko
        from host_key_store import trust_host_key, configure_client, UnknownHostKeyError
        key=paramiko.RSAKey.generate(1024);path=self.root/'known_hosts'
        with self.assertRaises(ValueError):trust_host_key(path,'a\nb',key.get_name(),key.get_base64())
        cli=paramiko.SSHClient();configure_client(cli,path)
        with self.assertRaises(UnknownHostKeyError):cli._policy.missing_host_key(cli,'host',key)
        trust_host_key(path,'host',key.get_name(),key.get_base64())
        self.assertIn('host',paramiko.HostKeys(str(path)))

if __name__=='__main__': unittest.main()
