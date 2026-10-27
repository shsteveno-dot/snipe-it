#!/usr/bin/env python3
"""Re-pin the locks to the files of this repository that the image build checks.

The build refuses to run when composer.lock, snipeit-runtime/go.mod or the slice
definitions differ from the bytes recorded in input-lock.<arch>.json. After you
change one of them, run this script from the repository root:

    python3 docker/chiseled/repin_app_inputs.py          # rewrite the locks
    python3 docker/chiseled/repin_app_inputs.py --check  # only report drift

It updates, for every architecture lock: the composer.lock, go.mod and slice
archive digests and sizes, then the digests of the lock files themselves in
accepted-inputs.json and runtime_inputs_test.py. It does not touch package
indexes or package digests; those are only changed by capture_snapshot.py.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent
ARCHITECTURES = ('amd64', 'arm64')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def slice_archive():
    """The same archive fetch_inputs.py builds from slices/*.yaml."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive_file:
        for path in sorted((BASE / 'slices').glob('*.yaml')):
            data = path.read_bytes()
            entry = tarfile.TarInfo(path.name)
            entry.mode = 0o644
            entry.size = len(data)
            archive_file.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def current_inputs():
    sources = {
        'composer_lock': (ROOT / 'composer.lock').read_bytes(),
        'go_mod': (ROOT / 'docker' / 'snipeit-runtime' / 'go.mod').read_bytes(),
        'custom_sdfs': slice_archive(),
    }
    return {name: (digest(data), len(data)) for name, data in sources.items()}


def repin_lock(text, lock, wanted):
    """Replace digests and sizes in the lock's text, so formatting is unchanged."""
    for name, (new_digest, new_size) in wanted.items():
        old_digest = lock['inputs'][name]['sha256']
        if old_digest != new_digest:
            text = text.replace(old_digest, new_digest)
        pattern = re.compile(r'("%s": \{\s*"sha256": "%s",\s*"size": )\d+' % (name, new_digest))
        text, count = pattern.subn(lambda m: m.group(1) + str(new_size), text)
        if count != 1:
            raise SystemExit('lock layout changed: %s input block not found exactly once' % name)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true', help='report drift and exit 1 instead of writing')
    args = parser.parse_args()

    wanted = current_inputs()
    drift = False
    lock_digests = {}
    for architecture in ARCHITECTURES:
        path = BASE / ('input-lock.%s.json' % architecture)
        text = path.read_text(encoding='utf-8')
        lock = json.loads(text)
        new_text = repin_lock(text, lock, wanted)
        if new_text != text:
            drift = True
            print('%s: lock out of date' % path.name)
            if not args.check:
                path.write_bytes(new_text.encode('utf-8'))
        lock_digests[architecture] = digest(new_text.encode('utf-8'))

    accepted_path = BASE / 'accepted-inputs.json'
    accepted = accepted_path.read_text(encoding='utf-8')
    new_accepted = accepted
    test_path = BASE / 'runtime_inputs_test.py'
    test_text = test_path.read_text(encoding='utf-8')
    new_test = test_text
    for architecture, new_digest in lock_digests.items():
        old_digest = json.loads(accepted)['lock_sha256'][architecture]
        if old_digest != new_digest:
            drift = True
            print('accepted lock digest for %s is out of date' % architecture)
            new_accepted = new_accepted.replace(old_digest, new_digest)
            new_test = new_test.replace(old_digest, new_digest)
    if not args.check:
        accepted_path.write_bytes(new_accepted.encode('utf-8'))
        test_path.write_bytes(new_test.encode('utf-8'))

    if drift and args.check:
        sys.exit(1)
    print('locks are up to date' if not drift else 'locks rewritten')


if __name__ == '__main__':
    main()
