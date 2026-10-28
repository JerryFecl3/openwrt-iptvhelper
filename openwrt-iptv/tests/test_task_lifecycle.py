import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'iptv-client'), str(root / 'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import app, lifecycle, task_lifecycle
import control


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        if sys.platform=='win32':
            fake=type('F',(),{'LOCK_EX':1,'LOCK_NB':2,'flock':staticmethod(lambda *a:None)})
            context=patch.dict(sys.modules,{'fcntl':fake});context.start();self.addCleanup(context.stop)
    def test_only_exact_manual_worker_is_signalled(self):
        with tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
            proc = Path(tmp)
            for pid, args in enumerate((
                b'python3\0/usr/lib/iptvhelper-app/app.py\0manual-worker\0' + b'4\0',
                b'python3\0/usr/lib/iptvhelper-app/app.py\0daemon\0',
                b'python3\0/other/app.py\0manual-worker\0'), 101):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / 'cmdline').write_bytes(args)
            with patch.object(task_lifecycle.os, 'kill') as kill:
                task_lifecycle.stop_manual_workers(proc)
            kill.assert_called_once_with(101, task_lifecycle.signal.SIGTERM)
    def test_master_switch_rejects_maintenance_without_mutation(self):
        from contextlib import nullcontext
        for enabled in (True,False):
            with patch.object(control,'operation',return_value=nullcontext()),patch.object(control,'MAINTENANCE') as marker,patch.object(control,'run') as run:
                marker.exists.return_value=True
                with self.assertRaises(RuntimeError):control.change(enabled)
                run.assert_not_called()
    def test_operation_lock_timeout(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            fake=type('F',(),dict(LOCK_EX=1,LOCK_NB=2,flock=Mock(side_effect=BlockingIOError)))
            with patch.dict(sys.modules,{'fcntl':fake}),self.assertRaises(RuntimeError):
                with task_lifecycle.operation(Path(tmp),timeout=0):self.fail('must not enter')

    def test_drain_retries_and_holds_lock_during_operation(self):
        with tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
            held = []
            def flock(fd, flags):
                held.append(fd)
                if len(held) == 1:raise BlockingIOError()
            fake = type('F', (), dict(LOCK_EX=1, LOCK_NB=2, flock=staticmethod(flock)))
            with patch.dict(sys.modules, {'fcntl': fake}), patch.object(task_lifecycle, 'stop_manual_workers') as stop, patch.object(task_lifecycle.time, 'sleep'):
                with task_lifecycle.drain(Path(tmp)):
                    self.assertFalse(held[-1].closed)
                self.assertEqual(stop.call_count, 2)
                self.assertTrue(held[-1].closed)

    def test_timeout_aborts_without_entering_operation(self):
        with tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
            fake = type('F', (), dict(LOCK_EX=1, LOCK_NB=2, flock=Mock(side_effect=BlockingIOError)))
            with patch.dict(sys.modules, {'fcntl': fake}), patch.object(task_lifecycle, 'stop_manual_workers'):
                with self.assertRaises(RuntimeError):
                    with task_lifecycle.drain(Path(tmp), timeout=0):
                        self.fail('unsafe mutation')

    def test_maintenance_blocks_manual_and_scheduled_collection(self):
        with tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
            path = Path(tmp); marker = path / 'maintenance'; marker.touch()
            fake = type('F', (), dict(LOCK_EX=1, LOCK_NB=2, flock=staticmethod(lambda *a: None)))
            with patch.dict(sys.modules, {'fcntl': fake}), patch.object(app, 'STATE', path), patch.object(app, 'MAINTENANCE', marker), patch.object(app, 'settings', return_value={}), patch.object(app.subprocess, 'Popen') as spawn, patch.object(app, '_attempt') as attempt:
                self.assertEqual(app.request_update()['reason'], 'maintenance')
                self.assertEqual(app.once(scheduled=True)['reason'], 'maintenance')
                spawn.assert_not_called(); attempt.assert_not_called()

    def test_failed_drain_preserves_marker_and_prevents_cleanup(self):
        for action in ('upgrade', 'remove'):
            with self.subTest(action=action), tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
                instance = lifecycle.Lifecycle(tmp, lambda args, **kw: subprocess.CompletedProcess(args, 0, '', ''))
                with patch.object(lifecycle, 'drain', side_effect=RuntimeError('busy')), patch.object(instance, 'remove_quiesced') as cleanup:
                    with self.assertRaises(RuntimeError):getattr(instance, action)()
                    cleanup.assert_not_called()
                self.assertTrue((Path(tmp) / 'var/run/iptvhelper-removing').exists())
                self.assertFalse((Path(tmp) / 'etc/iptvhelper-data').exists())
