import sys,unittest,subprocess
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import control,policy,app

class Tests(unittest.TestCase):
    def setUp(self):
        for context in (patch.object(control,'operation',side_effect=lambda:nullcontext()),patch.object(control,'MAINTENANCE'),patch.object(control,'run')):
            obj=context.start();self.addCleanup(context.stop)
        control.MAINTENANCE.exists.return_value=False
    def test_failed_start_never_reports_success_or_starts_app(self):
        with patch.object(control.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),patch.object(control.time,'monotonic',side_effect=[0,6]):
            with self.assertRaises(RuntimeError):control.change(True)
        self.assertFalse(any('/etc/init.d/iptvhelper-app' in call.args[0] for call in control.run.call_args_list))
    def test_failed_drain_does_not_remove_routes_or_recover(self):
        with patch.object(control,'drain',side_effect=RuntimeError('busy')),patch.object(policy,'remove_owned') as remove,patch.object(app,'recover_execution') as recover:
            with self.assertRaises(RuntimeError):control.change(False)
            remove.assert_not_called();recover.assert_not_called()
    def test_command_timeout_propagates(self):
        control.run.side_effect=subprocess.TimeoutExpired('service',5)
        with self.assertRaises(subprocess.TimeoutExpired):control.change(True)
    def test_successful_enable_checks_both_services(self):
        with patch.object(control.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as running:
            self.assertEqual(control.change(True),{'service_enabled':True})
            self.assertEqual([c.args[0] for c in running.call_args_list],[['/etc/init.d/iptvhelper-policy','running'],['/etc/init.d/iptvhelper-app','running']])
