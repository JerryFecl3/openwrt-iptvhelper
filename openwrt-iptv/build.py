"""Prepare a clean source tree; archives require an explicit --archive flag."""
import argparse,hashlib,json,os,shutil,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CLIENT_MODULES=('__init__','auth','catalog','client','collector','epg_store','network_dns','parsing','platform','publisher','transport')
EXECUTABLES=('etc/init.d/iptvhelper-relay','etc/init.d/iptvhelper-app','etc/init.d/iptvhelper-policy','etc/hotplug.d/iface/97-iptvhelper-policy','usr/libexec/rpcd/iptvhelper')

def prepare(destination=None):
    base=(ROOT/'build').resolve();base.mkdir(exist_ok=True)
    destination=Path(destination or base/'root')
    if destination.is_symlink() or destination.parent.resolve()!=base or destination.name in ('','..','.'):raise ValueError('Unsafe staging destination')
    stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=base))
    try:
        shutil.copytree(ROOT/'files',stage,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        client=stage/'usr/lib/iptvhelper-app/iptv_client';client.mkdir(parents=True,exist_ok=True)
        for name in CLIENT_MODULES:shutil.copyfile(ROOT.parent/'iptv-client/iptv_client'/(name+'.py'),client/(name+'.py'))
        for path in stage.rglob('*'):
            if not path.is_file():continue
            rel=path.relative_to(stage).as_posix()
            if rel in EXECUTABLES or rel.startswith(('lib/upgrade/keep.d/','etc/config/')):
                path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))
            path.chmod(0o755 if rel in EXECUTABLES else 0o600 if rel=='etc/config/iptvhelper' else 0o644)
        # The only recursive removal target is the checked direct child of build/.
        if destination.exists():shutil.rmtree(destination)
        stage.replace(destination)
        return destination
    finally:
        if stage.exists():shutil.rmtree(stage)

def archive(stage):
    target=ROOT/'build/root.tar.gz'
    with tarfile.open(target,'w:gz') as tar:
        for path in stage.rglob('*'):
            if not path.is_file():continue
            rel=path.relative_to(stage).as_posix();info=tar.gettarinfo(str(path),arcname=rel)
            info.uid=info.gid=0;info.uname=info.gname='root'
            info.mode=0o755 if rel in EXECUTABLES else 0o600 if rel=='etc/config/iptvhelper' else 0o644
            with path.open('rb') as f:tar.addfile(info,f)
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',action='store_true');args=parser.parse_args()
    stage=prepare();print(archive(stage) if args.archive else stage)
