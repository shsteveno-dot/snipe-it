#!/usr/bin/env python3
"""Generate per-shard phpunit configs and the volume init PHP snippet."""
import json, os, re, sys
from pathlib import Path
root = Path(sys.argv[1]); out = Path(sys.argv[2])
files = sorted(str(p.relative_to(root)) for p in (root/'tests').rglob('*Test.php'))
abm = [f for f in files if '/SyncAdapters/AppleBusinessManager/' in f]
sync = [f for f in files if '/SyncAdapters/' in f and f not in abm]
rest = [f for f in files if f not in abm and f not in sync]
shards = {f'shard{i}': [] for i in range(4)}; load = {k: 0 for k in shards}
for f in sorted(rest, key=lambda f: -(root/f).stat().st_size):
    k = min(load, key=load.get); shards[k].append(f); load[k] += (root/f).stat().st_size
# keep the round-16 ordering condition inside one shard: ShelllessSchedulerTest before RestoreToRemoteDiskTest
a, b = 'tests/Feature/Console/ShelllessSchedulerTest.php', 'tests/Feature/S3Compatibility/RestoreToRemoteDiskTest.php'
ka = next(k for k in shards if a in shards[k]); kb = next(k for k in shards if b in shards[k])
if ka != kb:
    shards[kb].remove(b); shards[ka].append(b)
shards['syncrest'] = sync
for i, f in enumerate(abm): shards[f'abm{i}'] = [f]
src = (root/'phpunit.xml').read_text()
for name, fl in shards.items():
    fl = sorted(fl)
    suite = '<testsuites>\n    <testsuite name="shard">\n' + ''.join(f'      <file>./{f}</file>\n' for f in fl) + '    </testsuite>\n  </testsuites>'
    xml = re.sub(r'<testsuites>.*?</testsuites>', suite, src, flags=re.S)
    xml = xml.replace('cacheDirectory=".phpunit.cache"', 'cacheDirectory="/tmp/.phpunit.cache"')
    (out/f'{name}.xml').write_text(xml)
    print(name, len(fl), 'files')
startup = (root/'docker/snipeit-runtime/internal/startup/startup.go').read_text()
m = re.search(r'\bvar\s+dataDirs\s*=\s*\[\]string\s*\{([^{}]*)\}', startup)
dirs = ['']
for p in re.findall(r'"([^"]+)"', m.group(1)):
    parts = p.split('/')
    for n in range(1, len(parts)+1):
        q = '/'.join(parts[:n])
        if q not in dirs: dirs.append(q)
(out/'init.php').write_text("<?php foreach(json_decode('" + json.dumps(dirs) + "') as $p){$d='/var/lib/snipeit'.($p?'/'.$p:'');@mkdir($d,0775,true);chown($d,10000);chgrp($d,50);}\n")
print('dataDirs', len(dirs))
