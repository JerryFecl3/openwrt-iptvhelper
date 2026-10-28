"""Drain detached collectors before package files are replaced or removed."""
import os
import signal
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

MAINTENANCE = Path('/var/run/iptvhelper-removing')

@contextmanager
def operation(root=Path('/'), timeout=5):
    import fcntl
    path=Path(root)/'var/run/iptvhelper-control.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+timeout
    with path.open('a') as lock:
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('Another service operation is in progress')
                time.sleep(0.1)
        yield

def serialized(method):
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with operation(self.root):return method(self,*args,**kwargs)
    return wrapped


def stop_manual_workers(proc=Path('/proc')):
    for path in proc.glob('[0-9]*/cmdline'):
        try:
            args = path.read_bytes().split(b'\0')
            # Match our entry point and subcommand, not arbitrary substrings.
            if len(args) >= 3 and args[1:3] == [b'/usr/lib/iptvhelper-app/app.py', b'manual-worker']:
                os.kill(int(path.parent.name), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass


@contextmanager
def drain(root=Path('/'), timeout=15):
    import fcntl
    path = Path(root) / 'var/lib/iptvhelper-app/app.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open('a') as lock:
        while True:
            # Repeat to cover a request which passed its gate just before the
            # maintenance marker was created and has not spawned its child yet.
            stop_manual_workers(Path(root) / 'proc')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Collector did not stop; package operation aborted')
                time.sleep(0.1)
        yield
