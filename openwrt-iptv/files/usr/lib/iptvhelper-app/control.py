"""Persistent master switch; serialized with package lifecycle operations."""
import subprocess,time
from task_lifecycle import operation,drain,MAINTENANCE

def run(args):
    return subprocess.run(args,check=True,timeout=5)

def change(enabled):
    with operation():
        if MAINTENANCE.exists():raise RuntimeError('Package maintenance is in progress')
        run(['uci','set','iptvhelper.main.service_enabled='+('1' if enabled else '0')])
        run(['uci','commit','iptvhelper'])
        if enabled:
            for service in ('iptvhelper-policy','iptvhelper-app'):
                run(['/etc/init.d/'+service,'enable'])
                run(['/etc/init.d/'+service,'start'])
                deadline=time.monotonic()+5
                while subprocess.run(['/etc/init.d/'+service,'running'],timeout=2).returncode:
                    if time.monotonic()>=deadline:raise RuntimeError('Service did not start: '+service)
                    time.sleep(0.1)
        else:
            for service in ('iptvhelper-app','iptvhelper-policy','iptvhelper-relay'):
                run(['/etc/init.d/'+service,'stop'])
                run(['/etc/init.d/'+service,'disable'])
            with drain():
                import policy
                policy.remove_owned()
            from app import recover_execution
            recover_execution()
        return {'service_enabled':enabled}
