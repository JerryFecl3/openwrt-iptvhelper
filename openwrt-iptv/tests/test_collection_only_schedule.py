import sys,unittest,datetime as dt,tempfile,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
from scheduler import Scheduler,daily_times,DEFAULT_TIMES
import app

def at(s):return dt.datetime.fromisoformat(s).timestamp()
class DailyScheduleTests(unittest.TestCase):
    def planner(self,state=None):
        p=Scheduler(state);p.configure({'collect_times':['00:05','06:05','12:05','18:05']});return p
    def test_validation_and_defaults(self):
        self.assertEqual(daily_times({}),['08:00'])
        self.assertEqual(daily_times({'collect_times':['18:05','00:05','18:05']}),['00:05','18:05'])
        for value in ([],['24:00'],['6:05'],['12:60'],['abc']):
            with self.assertRaises(ValueError):daily_times({'collect_times':value})
    def test_idle_disabled_never_contacts_platform(self):
        p=self.planner()
        for now in (0,3600,86400,10**9):self.assertIsNone(p.due(now,False))
    def test_failed_slot_is_consumed_and_restart_safe(self):
        p=self.planner();now=at('2026-10-27T12:06:00')
        self.assertEqual(p.due(now,True),'collect');p.started(now,'collect',True,'scheduled')
        p.finished(now+60,'collect',{'phase':'failed'},True)
        p=self.planner(p.dump())
        self.assertIsNone(p.due(at('2026-10-27T18:04:59'),True))
        self.assertEqual(p.due(at('2026-10-27T18:05:00'),True),'collect')
    def test_crash_consumes_slot_without_replaying(self):
        p=self.planner();now=at('2026-10-27T12:06:00');p.started(now,'collect',True,'scheduled')
        p=self.planner(p.dump());p.recover();self.assertEqual(p.history[-1]['result'],'interrupted')
        self.assertIsNone(p.due(now+300,True))
    def test_manual_does_not_shift_next_slot(self):
        p=self.planner();now=at('2026-10-27T13:00:00');p.started(now,'collect',True,'manual')
        p.finished(now+30,'collect',{'phase':'ready'},True)
        self.assertEqual(p.project(now+30,True,lambda x:x)['next_run'],at('2026-10-27T18:05:00'))
    def test_long_manual_covers_crossed_slots(self):
        p=self.planner();p.started(at('2026-10-27T17:59:00'),'collect',True,'manual')
        p.finished(at('2026-10-27T18:10:00'),'collect',{'phase':'failed'},True)
        self.assertIsNone(p.due(at('2026-10-27T18:12:00'),True))
    def test_missed_days_coalesce_and_clock_rollback(self):
        p=self.planner();p.started(at('2026-10-27T19:00:00'),'collect',True,'scheduled')
        p.finished(at('2026-10-27T19:01:00'),'collect',{'phase':'ready'},True)
        self.assertIsNone(p.due(at('2026-10-26T19:00:00'),True))
        now=at('2026-10-30T07:00:00');self.assertEqual(p.due(now,True),'collect')
        p.started(now,'collect',True,'scheduled');p.finished(now+1,'collect',{'phase':'ready'},True)
        self.assertIsNone(p.due(now+2,True))
        self.assertEqual(len(p.history),2)
    def test_midnight_next_slot(self):
        p=self.planner();now=at('2026-10-27T23:59:00');p.started(now,'collect',True,'manual')
        self.assertEqual(p.project(now,True,lambda x:x)['next_run'],at('2026-10-28T00:05:00'))
    def test_old_retry_state_is_ignored(self):
        p=self.planner({'pending':'collect','retry_kind':'collect','next_retry':0})
        self.assertIsNone(p.due(0,False))

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.settings_patch=patch.object(app,'settings',return_value={})
        self.settings_patch.start();self.addCleanup(self.settings_patch.stop)
    def test_start_is_durable_before_attempt_and_retries_hold_lock(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp);held=[]
            class F:
                LOCK_EX=1;LOCK_NB=2
                @staticmethod
                def flock(fd,flags):held.append(fd)
            def attempt(mode):
                saved=json.loads((path/'ledger').read_text())
                self.assertEqual(saved['history'][-1]['result'],'running')
                self.assertFalse(held[0].closed)
                return {'phase':'failed'}
            with patch.object(app,'STATE',path),patch.object(app,'SCHEDULE_FILE',path/'ledger'),patch.object(app,'effective_settings',return_value={'enabled':'1','_network_ready':True}),patch.object(app,'_attempt',side_effect=attempt) as run,patch.object(app.time,'sleep') as sleep,patch.dict(sys.modules,{'fcntl':F}):
                result=app.once();self.assertEqual(run.call_count,3);self.assertEqual(sleep.call_count,2)
            self.assertEqual(result['attempts'],3);self.assertTrue(held[0].closed)
            saved=json.loads((path/'ledger').read_text());self.assertEqual(saved['history'][-1]['result'],'failed')
    def test_busy_lock_never_consumes_slot_or_manual_request(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp);(path/'refresh.request').touch()
            class F:
                LOCK_EX=1;LOCK_NB=2
                @staticmethod
                def flock(*args):raise BlockingIOError()
            with patch.object(app,'STATE',path),patch.object(app,'SCHEDULE_FILE',path/'ledger'),patch.dict(sys.modules,{'fcntl':F}):
                self.assertEqual(app.once()['reason'],'already_running')
            self.assertFalse((path/'ledger').exists());self.assertTrue((path/'refresh.request').exists())
    def test_manual_launch_passes_held_lock_without_queue(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp);held=[]
            class F:
                LOCK_EX=1;LOCK_NB=2
                @staticmethod
                def flock(fd,flags):held.append(fd)
            def spawn(args,**kw):
                self.assertFalse(held[0].closed)
                self.assertEqual(kw['pass_fds'],(held[0].fileno(),))
                self.assertEqual(args[-2],'manual-worker')
                self.assertTrue(kw['start_new_session'])
            with patch.object(app,'STATE',path),patch.object(app.subprocess,'Popen',side_effect=spawn) as run,patch.dict(sys.modules,{'fcntl':F}):
                self.assertTrue(app.request_update()['accepted']);run.assert_called_once()
            self.assertFalse((path/'refresh.request').exists())
    def test_busy_manual_launch_does_not_spawn(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            class F:
                LOCK_EX=1;LOCK_NB=2
                @staticmethod
                def flock(*args):raise BlockingIOError()
            with patch.object(app,'STATE',Path(tmp)),patch.object(app.subprocess,'Popen') as run,patch.dict(sys.modules,{'fcntl':F}):
                self.assertEqual(app.request_update()['reason'],'already_running');run.assert_not_called()
