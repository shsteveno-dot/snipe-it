#!/usr/bin/env python3
"""Task 4.4: functional regression of one image on an internal network (no egress).

Usage:
  python3 -I regression.py --self-test               # matcher must reject an unsent marker
  python3 -I regression.py <image> [--out regression.json --label <key>]
Checks: web setup + login dashboard, schedule:run exit 0, SMTP marker delivery to
sink@example.invalid, non-empty backup dump, no OOM kill under 1536m, no OPcache files
under /var/www/html or /var/lib/snipeit. All containers/networks/volumes are removed.
"""
import argparse
import json
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import HERE, Stack, docker, host_path  # noqa: E402

FILE_SCAN = ('$n=0;foreach(["/var/www/html","/var/lib/snipeit"] as $d){$it=new RecursiveIteratorIterator('
             'new RecursiveDirectoryIterator($d,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::SELF_FIRST);'
             'foreach($it as $f){$p=$f->getPathname();if(preg_match("~/(opcache|[0-9a-f]{32})/|\\.php\\.bin$~",$p))$n++;}}'
             'echo $n;')


def delivered(messages, marker):
    return [m for m in messages if marker in m.get('data', '') and 'sink@example.invalid' in m.get('recipient', '')]


def smtp_messages(stack):
    code = f'echo file_get_contents("http://{stack.smtp}:8025/");'
    return json.loads(stack.php(code).stdout or '[]')


def client(stack, *args):
    result = docker('run', '--rm', '--network', stack.net, '-v', host_path(HERE / 'webclient.py') + ':/w.py:ro',
                    'python:3.12-slim', 'python', '-u', '/w.py', args[0], f'http://{stack.app}:8080', *args[1:],
                    check=False, timeout=900)
    return result.returncode, json.loads(result.stdout.strip().splitlines()[-1])


def run(image):
    password = 'Rg-' + secrets.token_hex(8) + '-Aa1!'
    checks, details = {}, {}
    mounts = [(HERE / 'mail.php', '/verification/mail.php')]
    with Stack(image, s3=True, smtp=True, mounts=mounts, mem_limit='1536m') as stack:
        code, setup = client(stack, 'setup', 'admin', password)
        details['web'] = setup
        checks['web_setup_and_dashboard_login'] = code == 0 and setup.get('dashboard_ok') is True
        schedule = docker('exec', stack.app, '/usr/bin/php', '/var/www/html/artisan', 'schedule:run', check=False)
        details['schedule_run_exit'] = schedule.returncode
        checks['schedule_run_exit_0'] = schedule.returncode == 0
        marker = 'opcache-regression-' + secrets.token_hex(6)
        sent = docker('exec', stack.app, '/usr/bin/php', '/verification/mail.php', marker, check=False)
        found = delivered(smtp_messages(stack), marker)
        details['mail'] = {'marker': marker, 'send_exit': sent.returncode, 'matches': len(found),
                           'recipient': found[0]['recipient'] if found else None,
                           'sender': found[0]['sender'] if found else None}
        checks['smtp_marker_delivered'] = sent.returncode == 0 and len(found) >= 1
        backup = docker('exec', stack.app, '/usr/bin/php', '/var/www/html/artisan', 'snipeit:backup', check=False)
        found_zip = json.loads(stack.php(
            '$z=[];foreach(new RecursiveIteratorIterator(new RecursiveDirectoryIterator("/var/lib/snipeit",'
            'FilesystemIterator::SKIP_DOTS)) as $f){if(substr($f,-4)===".zip")$z[(string)$f]=$f->getSize();}'
            'echo json_encode($z);', check=False).stdout or '{}')
        size = max(found_zip.values(), default=0)
        details['backup'] = {'exit': backup.returncode, 'zips': found_zip, 'latest_zip_bytes': size,
                             'output_tail': (backup.stdout or '')[-800:]}
        checks['backup_dump_non_empty'] = backup.returncode == 0 and int(size or 0) > 0
        details['opcache_like_files'] = int(stack.php(FILE_SCAN).stdout or 0)
        checks['no_opcache_files_written'] = details['opcache_like_files'] == 0
        state = json.loads(docker('inspect', stack.app).stdout)[0]['State']
        checks['not_oom_killed_under_1536m'] = state['OOMKilled'] is False and state['Running'] is True
    leftovers = docker('ps', '-a', '--filter', f'name={stack.prefix}', '-q').stdout.strip() + \
        docker('network', 'ls', '--filter', f'name={stack.prefix}', '-q').stdout.strip()
    checks['cleanup_complete'] = leftovers == ''
    return checks, details


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('image', nargs='?')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--label')
    args = parser.parse_args(argv)
    if args.self_test:
        messages = [{'recipient': 'RCPT TO:<sink@example.invalid>', 'data': 'Subject: other-marker'}]
        hit = delivered(messages, 'never-sent-marker')
        print(json.dumps({'self_test_matches_for_unsent_marker': len(hit)}))
        assert not hit, 'matcher matched a message for a marker that was never sent'
        return 0
    checks, details = run(args.image)
    passed = all(checks.values())
    result = {'image': args.image, 'checks': checks, 'details': details, 'result': 'pass' if passed else 'fail'}
    if args.out:
        data = json.loads(args.out.read_text()) if args.out.exists() else {}
        data[args.label or args.image] = result
        args.out.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
