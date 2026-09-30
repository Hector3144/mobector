"""Bounded SSH writer. No socket I/O in the GUI thread."""
import threading
import socket
import time
from collections import deque


class AsyncChannelWriter:
    def __init__(self, channel, on_error, max_bytes=2 * 1024 * 1024):
        self.channel = channel
        self.on_error = on_error
        self.max_bytes = max_bytes
        self._condition = threading.Condition()
        self._queue = deque()
        self._bytes = 0
        self._stopped = False
        self.thread = threading.Thread(target=self._run, daemon=True, name='MobHector-PTY-writer')
        self.thread.start()

    def submit(self, data):
        with self._condition:
            if self._stopped or self.channel.closed:
                return False
            if self._bytes + len(data) > self.max_bytes:
                return False
            self._queue.append(bytes(data))
            self._bytes += len(data)
            self._condition.notify()
            return True

    def stop(self):
        with self._condition:
            self._stopped = True
            self._queue.clear()
            self._bytes = 0
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopped or self._queue)
                if self._stopped:
                    return
                data = self._queue.popleft()
            try:
                send = getattr(self.channel, "send", None)
                if not callable(send):
                    self.channel.sendall(data)
                else:
                    offset = 0
                    last_progress = time.monotonic()
                    while offset < len(data):
                        with self._condition:
                            if self._stopped:
                                return
                        try:
                            count = send(data[offset:offset + 16384])
                        except socket.timeout:
                            if time.monotonic() - last_progress > 30:
                                raise TimeoutError("SSH no acepta datos desde hace 30 segundos")
                            continue
                        if not count:
                            raise ConnectionError("Canal SSH cerrado")
                        offset += count
                        last_progress = time.monotonic()
            except Exception as exc:
                with self._condition:
                    report = not self._stopped
                self.stop()
                if report:
                    self.on_error(str(exc))
                return
            with self._condition:
                self._bytes = max(0, self._bytes - len(data))
