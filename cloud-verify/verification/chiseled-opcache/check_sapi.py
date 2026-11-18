#!/usr/bin/env python3
"""Task 4.2: check OPcache state of the CLI and Apache SAPIs of one image.

Usage: python3 -I check_sapi.py <image> [--out sapi.json --label <key>]
Exit 0 only when every check passes.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import HERE, PLATFORM_ARGS, Stack, docker  # noqa: E402

PROBE = HERE / '__opcache_probe.php'
PROBE_TARGET = '/var/www/html/public/__opcache_probe.php'
OPCACHE_ERRORS = re.compile(r'(opcache|Zend OPcache).*(fail|error|unable|cannot)', re.I)


def cli_checks(image):
    run = lambda *a: docker('run', '--rm', *PLATFORM_ARGS, '--network', 'none', '--user', '10000:50', '--cap-drop', 'ALL',
                            '--security-opt', 'no-new-privileges:true', '--entrypoint', '/usr/bin/php',
                            image, *a, check=False).stdout
    modules = run('-m')
    zend = modules.split('[Zend Modules]', 1)[1] if '[Zend Modules]' in modules else ''
    status = json.loads(run('-r', 'echo json_encode(["enabled"=>function_exists("opcache_get_status")'
                                  '&&(opcache_get_status(false)["opcache_enabled"]??false),'
                                  '"jit"=>ini_get("opcache.jit"),"file_cache"=>ini_get("opcache.file_cache")]);'))
    return {
        'zend_modules_lists_opcache': 'Zend OPcache' in zend,
        'version_mentions_opcache': 'with Zend OPcache' in run('-v'),
        'opcache_enabled': status['enabled'] is True,
        'jit_off': status['jit'] in ('off', '0', '', 'disable'),
        'file_cache_empty': status['file_cache'] in ('', False, None),
    }


def apache_checks(image):
    with Stack(image, mounts=[(PROBE, PROBE_TARGET)]) as stack:
        for _ in range(20):
            stack.http('/__opcache_probe.php')
        probe = json.loads(stack.http('/__opcache_probe.php')['body'])
        errors = [line for line in stack.logs().splitlines() if OPCACHE_ERRORS.search(line)]
    return {
        'sapi_is_apache': probe['sapi'] == 'apache2handler',
        'opcache_enabled': probe['enabled'] is True,
        'hits_after_20_requests': (probe['hits'] or 0) > 0,
        'jit_off': probe['jit'] in ('off', '0', '', 'disable'),
        'file_cache_empty': probe['file_cache'] in ('', False, None),
        'no_opcache_errors_in_log': not errors,
    }, probe, errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--label')
    args = parser.parse_args(argv)
    cli = cli_checks(args.image)
    apache, probe, errors = apache_checks(args.image)
    passed = all(cli.values()) and all(apache.values())
    result = {'image': args.image, 'image_id': docker('image', 'inspect', '-f', '{{.Id}}', args.image).stdout.strip(),
              'cli': cli, 'apache': apache, 'apache_probe': probe, 'opcache_log_errors': errors,
              'result': 'pass' if passed else 'fail'}
    if args.out:
        data = json.loads(args.out.read_text()) if args.out.exists() else {}
        data[args.label or args.image] = result
        args.out.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
