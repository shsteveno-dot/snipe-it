#!/usr/bin/env python3
"""Task 4.3: runtime invariants of one image (shell-less, no package manager/compiler, user, entrypoint).

Usage: python3 -I check_invariants.py <image> [--boot] [--out invariants.json --label <key>]
--boot additionally starts the image on an internal network with the production security
options and requires init to succeed and /health to report ok.
Exit 0 only when every check passes.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import PLATFORM_ARGS, Stack, docker  # noqa: E402

FORBIDDEN = ['bin/sh', 'usr/bin/sh', 'bin/bash', 'usr/bin/bash', 'bin/dash', 'usr/bin/dash',
             'usr/bin/apt', 'usr/bin/apt-get', 'usr/bin/dpkg', 'usr/bin/gcc', 'usr/bin/cc']


def rootfs_names(image):
    container = docker('create', *PLATFORM_ARGS, image).stdout.strip()
    try:
        data = docker_bytes('export', container)
    finally:
        docker('rm', '-f', container, check=False)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {name.lstrip('./') for name in archive.getnames()}


def docker_bytes(*args):
    import subprocess
    from stack import ENV
    return subprocess.run(['docker', *args], check=True, stdout=subprocess.PIPE, env=ENV).stdout


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('--boot', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--label')
    args = parser.parse_args(argv)
    config = json.loads(docker('image', 'inspect', args.image).stdout)[0]['Config']
    names = rootfs_names(args.image)
    present = sorted(path for path in FORBIDDEN if path in names)
    checks = {
        'no_shell_package_manager_or_compiler': not present,
        'user_10000_50': config.get('User') == '10000:50',
        'entrypoint_supervisor': config.get('Entrypoint') == ['/snipeit-supervisor'],
    }
    if args.boot:
        try:
            with Stack(args.image):
                checks['boot_with_cap_drop_all_and_health_ok'] = True
        except RuntimeError as error:
            checks['boot_with_cap_drop_all_and_health_ok'] = False
            print('boot failed:', str(error)[-1500:], file=sys.stderr)
    passed = all(checks.values())
    result = {'image': args.image, 'checks': checks, 'forbidden_present': present,
              'user': config.get('User'), 'entrypoint': config.get('Entrypoint'),
              'result': 'pass' if passed else 'fail'}
    if args.out:
        data = json.loads(args.out.read_text()) if args.out.exists() else {}
        data[args.label or args.image] = result
        args.out.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
