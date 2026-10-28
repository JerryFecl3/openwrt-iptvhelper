import importlib.util,json,time,unittest
from pathlib import Path
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('routing_policy',root/'files/usr/lib/iptvhelper-app/policy.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.name='iptv'
        self.st={'up':True,'l3_device':'eth3','ipv4-address':[{'address':'10.128.158.22','mask':20}],
                 'inactive':{'route':[{'mask':0,'nexthop':'10.128.144.1'}]}}
        self.rules=[{'priority':100,'oif':'eth3','table':'42420'},{'priority':101,'oif':'eth3','action':'unreachable'}]
        self.routes=[{'dst':'10.128.144.0/20','dev':'eth3','protocol':'242','metric':10},
                     {'dst':'default','gateway':'10.128.144.1','dev':'eth3','protocol':'242','metric':10},
                     {'dst':'default','type':'unreachable','protocol':'242','metric':42760}]
        self.writes=[]
        self.saved=[]
    def run_cmd(self,*args):
        if args==('uci','-q','get','iptvhelper.main.route_table'):return '42420'
        if args==('ip','-4','route','show','table','42420'):return 'default via 10.128.144.1 dev eth3'
        if args[:3]==('ubus','call','uci'):return json.dumps({'values':{'hostname':'test'}})
        if args[:3]==('ubus','call','network.device'):return json.dumps({'macaddr':'02:00:00:00:00:01'})
        if args==('uci','-q','get','iptvhelper.main.interface'):return self.name
        if args[:2]==('ubus','call'):
            self.assertEqual(args[2],'network.interface.'+self.name)
            return json.dumps(self.st)
        if args==('ip','-j','-4','rule','show'):return json.dumps(self.rules)
        if args==('ip','-j','-4','route','show','table','42420'):return json.dumps(self.routes)
        if args==('ip','-j','-4','route','show','table','main'):return json.dumps([{'dst':'default','dev':'eth5'}])
        self.writes.append(args)
        self.assertNotIn('main',args)
        return ''
    def reconcile(self):
        with patch.object(p,'run',side_effect=self.run_cmd),patch.object(p,'read_state',return_value={'table':'42420','device':'eth3'}),patch.object(p,'save',side_effect=self.saved.append):
            return p.reconcile()
    def test_existing_routes_are_not_rewritten_every_poll(self):
        result=self.reconcile()
        self.assertTrue(result['up']);self.assertEqual(result['interface'],'iptv');self.assertEqual(self.writes,[])
    def test_configured_interface_and_device_switch(self):
        self.name='television';self.st['l3_device']='eth7'
        self.st['ipv4-address']=[{'address':'192.0.2.20','mask':24}]
        self.st['inactive']['route'][0]['nexthop']='192.0.2.1'
        result=self.reconcile()
        self.assertEqual(result['device'],'eth7');self.assertEqual(result['interface'],'television')
        self.assertEqual(result['guarded_devices'],['eth3','eth7'])
        guard=next(i for i,c in enumerate(self.writes) if 'unreachable' in c)
        withdraw=next(i for i,c in enumerate(self.writes) if c[:4]==('ip','-4','rule','del'))
        lookup=next(i for i,c in enumerate(self.writes) if c[:4]==('ip','-4','rule','add') and 'lookup' in c)
        self.assertLess(guard,withdraw);self.assertLess(withdraw,lookup)
        self.assertFalse(any(c[:4]==('ip','-4','rule','del') and '101' in c for c in self.writes))
        self.assertTrue(p.rule_owned(self.rules[1],result))
    def test_down_removes_usable_routes_but_keeps_guards(self):
        self.st={'up':False,'device':'eth3'}
        result=self.reconcile();self.assertFalse(result['up'])
        self.assertEqual(sum(c[:4]==('ip','-4','route','del') for c in self.writes),2)
        self.assertFalse(any('unreachable' in c and 'del' in c for c in self.writes))
    def test_management_device_is_rejected(self):
        self.st['l3_device']='eth5'
        result=self.reconcile();self.assertFalse(result['up'])
        self.assertIn('main default route',result['error'])
        self.assertFalse(any('eth5' in c for c in self.writes))
    def test_foreign_rule_is_not_touched(self):
        self.rules[0]['table']='100'
        with self.assertRaises(RuntimeError):self.reconcile()
        self.assertEqual(self.writes,[])
    def test_gateway_change_replaces_old_route(self):
        self.st['inactive']['route'][0]['nexthop']='10.128.144.2'
        result=self.reconcile()
        self.assertIn(('default','10.128.144.2'),result['routes'])
        self.assertTrue(any('replace' in c and '10.128.144.2' in c for c in self.writes))
    def test_cold_start_without_table(self):
        import subprocess
        self.rules=[]
        original=self.run_cmd
        def absent(*args):
            if args==('ip','-j','-4','route','show','table','42420'):
                raise subprocess.CalledProcessError(2,args)
            return original(*args)
        with patch.object(p,'run',side_effect=absent),patch.object(p,'read_state',return_value={}),patch.object(p,'save'):
            self.assertTrue(p.reconcile()['up'])
        self.assertTrue(any('unreachable' in c for c in self.writes))
