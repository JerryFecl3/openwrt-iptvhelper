import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'iptv-client'), str(root / 'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import lifecycle


class DisabledLifecycleTests(unittest.TestCase):
    def setUp(self):
        if sys.platform=='win32':
            fake=type('F',(),{'LOCK_EX':1,'LOCK_NB':2,'flock':staticmethod(lambda *a:None)})
            context=patch.dict(sys.modules,{'fcntl':fake});context.start();self.addCleanup(context.stop)
    def test_install_restores_and_respects_disabled_configuration(self):
        for restore in (None, 'upgrade-config.backup', 'retained-config'):
            with self.subTest(restore=restore), tempfile.TemporaryDirectory(dir=root / 'openwrt-iptv') as tmp:
                base = Path(tmp)
                config = base / 'etc/config/iptvhelper'
                config.parent.mkdir(parents=True)
                disabled = "config main 'main'\n option service_enabled '0'\n"
                config.write_text(disabled if restore is None else "option user_id ''\n")
                data = base / 'etc/iptvhelper-data'
                data.mkdir()
                if restore:
                    (data / restore).write_text(disabled)
                calls = []

                def runner(args, **kwargs):
                    calls.append(args)
                    if args[0] == 'uci':
                        self.assertEqual(config.read_text(), disabled)
                        return subprocess.CompletedProcess(args, 0, '0\n', '')
                    return subprocess.CompletedProcess(args, 0, '', '')

                instance = lifecycle.Lifecycle(base, runner)
                with patch.object(lifecycle, 'check_runtime'), patch.object(instance, 'refresh_rpc') as rpc, patch.object(instance, 'wait_running') as wait:
                    instance.install()
                rpc.assert_called_once()
                wait.assert_not_called()
                for name in ('iptvhelper-app', 'iptvhelper-policy', 'iptvhelper-relay'):
                    for action in ('stop', 'disable'):
                        self.assertIn([str(base / ('etc/init.d/' + name)), action], calls)
                self.assertFalse(any(c[-1] in ('enable', 'start', 'restart') for c in calls))

    def test_missing_flag_preserves_legacy_enabled_default(self):
        for code, value in ((1, ''), (0, ''), (0, '1\n')):
            runner = lambda args, **kw: subprocess.CompletedProcess(args, code, value, '')
            self.assertTrue(lifecycle.Lifecycle(runner=runner).enabled())


if __name__ == '__main__':
    unittest.main()
