#!/usr/bin/env python3
"""Cloud-only review-fixes runner. Results contain no command output or env."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(sys.argv[1]).resolve()
ROUND = sys.argv[2]
HERE = ROOT / 'cloud-verify' / 'review-fixes'
RESULT = HERE / ('results-' + ROUND + '.json')
RUN = 'review-' + uuid.uuid4().hex[:12]
LABEL = 'review-fixes.run=' + RUN
TMP = Path(tempfile.mkdtemp(prefix=RUN + '-'))
CONTAINERS, VOLUMES, NETWORKS, IMAGES = [], [], [], []
secret = base64.b64encode(os.urandom(32)).decode()
appkey = 'base64:' + secret
dbpass = uuid.uuid4().hex
data = {'round': ROUND, 'run_id': RUN, 'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'commit': None, 'platform': platform.platform(), 'candidate_image_id': None, 'test_image_id': None,
        'php_comparison': {}, 'tests': [], 'counts': {}, 'probes': {}, 'commands': [], 'errors': []}

def call(args, check=True, cwd=None, env=None):
    # Arguments can contain synthetic credentials: record only the executable and operation.
    data['commands'].append(' '.join(args[:2]))
    p = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and p.returncode:
        raise RuntimeError('command failed: ' + ' '.join(args[:2]) + ' (exit ' + str(p.returncode) + ')')
    return p

def docker(*args, check=True):
    return call(['docker', *map(str, args)], check=check)

def image_id(tag):
    return docker('image', 'inspect', '--format', '{{.Id}}', tag).stdout.strip()

def make_context(dest):
    dest.mkdir()
    archive = TMP / (dest.name + '.tar')
    with archive.open('wb') as out:
        subprocess.run(['git', '-C', str(ROOT), 'archive', 'HEAD'], stdout=out, check=True)
    with tarfile.open(archive) as tf:
        # The archive is produced by the current checkout, not an untrusted ZIP.
        tf.extractall(dest)

def prepare_cache(context):
    cache = TMP / 'composer-cache'
    cache.mkdir()
    lock = json.loads((context / 'composer.lock').read_text())
    for pkg in lock['packages'] + lock['packages-dev']:
        dist, source = pkg.get('dist', {}), pkg.get('source', {})
        url = dist.get('url', '')
        if not (url.startswith('https://api.github.com/') or url.startswith('https://codeload.github.com/')):
            continue
        source_url = source.get('url')
        ref = dist.get('reference') or source.get('reference')
        if not source_url or not ref:
            raise RuntimeError('locked package lacks source/reference: ' + pkg['name'])
        if source_url.startswith('git@github.com:'):
            source_url = 'https://github.com/' + source_url.split(':', 1)[1]
        mirror = TMP / ('git-' + hashlib.sha256(source_url.encode()).hexdigest())
        if not mirror.exists():
            call(['git', 'clone', '--mirror', '--filter=blob:none', source_url, str(mirror)])
        if call(['git', '--git-dir', str(mirror), 'cat-file', '-e', ref + '^{commit}'], check=False).returncode:
            call(['git', '--git-dir', str(mirror), 'fetch', 'origin', ref])
        path = cache / 'files' / pkg['name'] / (hashlib.sha1(url.encode()).hexdigest() + '.zip')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as out:
            subprocess.run(['git', '--git-dir', str(mirror), 'archive', '--format=zip', '--prefix=package/', ref],
                           stdout=out, check=True)
    return cache

def cached_dockerfile(context, fixture=False):
    path = context / 'Dockerfile.chiseled'
    text = path.read_text()
    needle = 'RUN php /usr/bin/composer install --no-dev --no-interaction --working-dir=/var/www/html'
    if needle not in text:
        raise RuntimeError('candidate composer insertion point not found')
    text = text.replace(needle, 'COPY --from=composercache --chown=10000:50 / /tmp/composer-cache/\n' + needle, 1)
    if fixture:
        needle = 'RUN python3 /chisel-inputs/prepare-app.py'
        if needle not in text:
            raise RuntimeError('prepare-app insertion point not found')
        text = text.replace(needle, 'COPY --from=stagingfixture / /var/www/html/storage/framework/backup-staging/\n' + needle, 1)
    path.write_text(text)

def build(context, tag, cache, target=None, fixture=None, dockerfile='Dockerfile.chiseled'):
    args = ['buildx', 'build', '--load', '--network', 'host', '--platform', 'linux/amd64',
            '--label', LABEL, '-t', tag, '-f', str(context / dockerfile)]
    if dockerfile == 'Dockerfile.chiseled':
        args += ['--build-context', 'composercache=' + str(cache)]
    if target:
        args += ['--target', target]
    if fixture:
        args += ['--build-context', 'stagingfixture=' + str(fixture)]
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'):
        if os.environ.get(key):
            args += ['--build-arg', key]
    args += [str(context)]
    docker(*args)
    IMAGES.append(tag)
    return image_id(tag)

def make_vendor(context, cache):
    # Development dependencies are installed in a disposable build helper, not
    # in the runtime under test. composer.lock is never modified.
    cmd = ['run', '--rm', '--network', 'host', '--label', LABEL,
           '-v', str(context) + ':/app', '-v', str(cache) + ':/tmp/composer-cache',
           '-w', '/app', '-e', 'COMPOSER_CACHE_DIR=/tmp/composer-cache',
           '-e', 'COMPOSER_ALLOW_SUPERUSER=1']
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'):
        if os.environ.get(key):
            cmd += ['-e', key]
    cmd += ['composer:2.10.3', 'composer', 'install', '--no-scripts', '--no-interaction',
            '--prefer-dist', '--ignore-platform-reqs']
    docker(*cmd)
    # The production image applies this same repository-owned patch after install.
    call(['python3', str(context / 'docker/snipeit-runtime/patch-dumper.py'),
          str(context / 'vendor/spatie/db-dumper/src/Databases/MySql.php')])
    return context / 'vendor'

def test_image(context, candidate, vendor, tag):
    docker('buildx', 'build', '--load', '--label', LABEL,
           '--build-arg', 'CANDIDATE=' + candidate, '--build-context', 'devvendor=' + str(vendor),
           '-f', context / 'cloud-verify/review-fixes/Dockerfile.test', '-t', tag, context)
    IMAGES.append(tag)
    return image_id(tag)

def run_php(image, *args, extra=(), check=False):
    return docker('run', '--rm', '--label', LABEL, *extra, '--entrypoint', '/usr/bin/php', image, *args, check=check)

def php_identity(candidate, test):
    checks = {'version': ['-v'], 'modules': ['-m'],
              'sha256': ['-r', "echo hash_file('sha256', '/usr/bin/php');"]}
    for name, args in checks.items():
        a = run_php(candidate, *args, check=True).stdout
        b = run_php(test, *args, check=True).stdout
        data['php_comparison'][name] = {'equal': a == b}
        if name == 'sha256':
            data['php_comparison'][name]['sha256'] = a.strip()
        if a != b:
            raise RuntimeError('candidate and test image PHP ' + name + ' differ')

def network():
    name = RUN + '-net'
    docker('network', 'create', '--internal', '--label', LABEL, name)
    NETWORKS.append(name)
    return name

def volume(name):
    v = RUN + '-' + name
    docker('volume', 'create', '--label', LABEL, v)
    VOLUMES.append(v)
    return v

def db_start(net):
    name = RUN + '-db'
    docker('run', '-d', '--name', name, '--label', LABEL, '--network', net,
           '-e', 'MYSQL_ROOT_PASSWORD=' + dbpass, '-e', 'MYSQL_ROOT_HOST=%',
           '-e', 'MYSQL_DATABASE=snipeit', 'mysql:8.4')
    CONTAINERS.append(name)
    for _ in range(120):
        p = docker('exec', name, 'mysqladmin', 'ping', '-h127.0.0.1', '-uroot',
                   '-p' + dbpass, '--silent', check=False)
        if p.returncode == 0:
            return name
        time.sleep(3)
    raise RuntimeError('MySQL readiness timed out')

def env_args(net, db, vol, results_dir):
    env = {'APP_KEY': appkey, 'APP_ENV': 'testing', 'APP_DEBUG': 'false', 'APP_URL': 'http://localhost',
           'DB_CONNECTION': 'mysql', 'DB_HOST': db, 'DB_PORT': '3306', 'DB_DATABASE': 'snipeit',
           'DB_USERNAME': 'root', 'DB_PASSWORD': dbpass, 'DB_DUMP_PATH': '/usr/bin',
           'CACHE_DRIVER': 'array', 'SESSION_DRIVER': 'array', 'QUEUE_CONNECTION': 'sync',
           'MAIL_MAILER': 'array', 'IMPORT_MEMORY_LIMIT': '2G', 'LDAP_MEM_LIM': '2G'}
    args = ['--network', net, '-v', vol + ':/var/lib/snipeit', '-v', str(results_dir) + ':/results']
    for key, value in env.items():
        args += ['-e', key + '=' + value]
    return args

def parse_junit(path, label):
    if not path.exists():
        data['errors'].append(label + ': no JUnit output')
        return
    cases = list(ET.parse(path).iter('testcase'))
    if not cases:
        data['errors'].append(label + ': JUnit contains no tests')
    for case in cases:
        child = next((x for x in case if x.tag in ('failure', 'error', 'skipped')), None)
        lines = [] if child is None else (child.get('message') or child.text or '').splitlines()
        message = lines[0] if lines else ''
        for value in (secret, appkey, dbpass):
            message = message.replace(value, '[redacted]')
        data['tests'].append({'run': label, 'name': case.get('classname', '') + '::' + case.get('name', ''),
                              'status': 'passed' if child is None else child.tag,
                              'message': message[:500]})

def phpunit(test, args, extra, file, label):
    p = run_php(test, '/var/www/html/vendor/bin/phpunit', '--colors=never', '--display-skipped',
                '--log-junit', '/results/' + file, *args, extra=extra)
    data['probes'][label + '_exit'] = p.returncode
    parse_junit(TMP / 'results' / file, label)

def probe_status(name, process):
    data['probes'][name] = {'exit_code': process.returncode, 'passed': process.returncode == 0}

def main():
    data['commit'] = call(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).stdout.strip()
    if call(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=no']).stdout.strip():
        raise RuntimeError('checkout must be clean before starting')
    context = TMP / 'context'
    make_context(context)
    cache = prepare_cache(context)
    vendor = make_vendor(context, cache)
    cached_dockerfile(context)
    candidate_tag = RUN + ':candidate'
    candidate = build(context, candidate_tag, cache)
    data['candidate_image_id'] = candidate
    test = test_image(context, candidate, vendor, RUN + ':test')
    data['test_image_id'] = test
    php_identity(candidate, test)
    net, vol = network(), volume('data')
    db = db_start(net)
    results = TMP / 'results'
    results.mkdir(mode=0o777)
    results.chmod(0o777)
    common = env_args(net, db, vol, results)
    # Populate the empty writable data volume with the directories expected by
    # Chiseled symlinks, without invoking a shell in the image.
    init = "foreach(['','data','data/private_uploads','data/uploads','dumps','keys','ssl'] as $p){$d='/var/lib/snipeit'.($p?'/'.$p:'');@mkdir($d,0775,true);chown($d,10000);chgrp($d,50);}"
    run_php(test, '-r', init, extra=common + ['--user', '0:0'], check=True)
    run_php(test, 'artisan', 'migrate', '--force', '--no-interaction', extra=common, check=True)
    run_php(test, 'artisan', 'passport:keys', '--force', '--no-interaction', extra=common, check=True)
    selector = 'finding|truncated|staged_copy|ou_rejection|ou_search|safety_backup|dn_separator|checks_crc'
    for label, testpath in [('ldap', 'tests/Unit/LdapTest.php'),
                            ('s3', 'tests/Feature/S3Compatibility'),
                            ('wizard', 'tests/Feature/Settings/LdapWizardTest.php')]:
        phpunit(test, ['--filter', selector, testpath], common, label + '-selected.xml', label + '_selected')
        phpunit(test, [testpath], common, label + '-suite.xml', label + '_suite')

    # Synthetic marker builds use a separate context, never real uploads.
    marked = TMP / 'marked'
    make_context(marked)
    marker = 'review-marker-' + uuid.uuid4().hex + '.txt'
    marker_dir = marked / 'storage/framework/backup-staging'
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / marker).write_text('synthetic marker')
    cached_dockerfile(marked)
    marked_id = build(marked, RUN + ':marked', cache)
    marked_test = test_image(context, marked_id, vendor, RUN + ':marked-test')
    php_identity(marked_id, marked_test)
    probe_path = HERE / 'staging-probe.php'
    probe_status('fr2_chiseled', run_php(marked_test, '/probe/staging-probe.php',
                 extra=['-v', str(probe_path) + ':/probe/staging-probe.php:ro']))
    regular = build(marked, RUN + ':regular', cache, dockerfile='Dockerfile')
    probe_status('fr2_regular', run_php(regular, '/probe/staging-probe.php',
                 extra=['-v', str(probe_path) + ':/probe/staging-probe.php:ro']))
    fixture = TMP / 'fixture'
    fixture.mkdir()
    (fixture / marker).write_text('synthetic marker')
    fixture_context = TMP / 'fixture-context'
    make_context(fixture_context)
    cached_dockerfile(fixture_context, fixture=True)
    fixture_image = build(fixture_context, RUN + ':fixture', cache, target='application', fixture=fixture)
    cid = docker('create', '--label', LABEL, fixture_image).stdout.strip()
    CONTAINERS.append(cid)
    cp = docker('cp', cid + ':/var/www/html/storage/framework/backup-staging', TMP / 'fixture-output', check=False)
    if cp.returncode != 0 and 'could not find the file' not in cp.stdout.lower():
        raise RuntimeError('preparation fixture inspection failed')
    data['probes']['fr2_prepare_app'] = {'passed': cp.returncode != 0, 'marker_directory_present': cp.returncode == 0}

    # Real Apache checks: each candidate has its own disposable data volume.
    for mode in ('valid', 'empty', 'unset', 'invalid'):
        name = RUN + '-apache-' + mode
        v = volume('apache-' + mode)
        args = ['run', '-d', '--name', name, '--label', LABEL, '--network', net,
                '-v', v + ':/var/lib/snipeit',
                '-v', str(HERE / 'remote-user.php') + ':/var/www/html/public/review-remote-user.php:ro',
                '-e', 'APP_KEY=' + appkey, '-e', 'APP_URL=http://' + name + ':8080',
                '-e', 'DB_HOST=' + db, '-e', 'DB_DATABASE=snipeit', '-e', 'DB_USERNAME=root',
                '-e', 'DB_PASSWORD=' + dbpass]
        if mode != 'unset':
            args += ['-e', 'REMOTE_LOGIN_FORWARDED_HEADER=' + ('Bad Header' if mode == 'invalid' else 'X-Review-User')]
        docker(*args, candidate)
        CONTAINERS.append(name)
        if mode == 'invalid':
            time.sleep(20)
            state = docker('inspect', '-f', '{{.State.Running}}', name).stdout.strip()
            code = docker('inspect', '-f', '{{.State.ExitCode}}', name).stdout.strip()
            data['probes']['fr8_invalid'] = {'passed': state == 'false' and code != '0',
                                             'running': state == 'true', 'exit_code': int(code)}
            continue
        endpoint = 'http://' + name + ':8080/review-remote-user.php'
        expected = 'review-user@example.invalid' if mode == 'valid' else ''
        header = '' if mode == 'empty' else 'review-user@example.invalid'
        probe = run_php(test, '/probe/apache-probe.php', endpoint, expected, header,
                        extra=common + ['-v', str(HERE / 'apache-probe.php') + ':/probe/apache-probe.php:ro'])
        # Retry startup, not an assertion failure indefinitely.
        for _ in range(40):
            if probe.returncode != 2:
                break
            time.sleep(3)
            probe = run_php(test, '/probe/apache-probe.php', endpoint, expected, header,
                            extra=common + ['-v', str(HERE / 'apache-probe.php') + ':/probe/apache-probe.php:ro'])
        probe_status('fr8_' + mode, probe)

    if ROUND == 'A':
        mutated = TMP / 'mutated'
        make_context(mutated)
        controller = mutated / 'app/Http/Controllers/SettingsController.php'
        source = controller.read_text()
        start = source.index("$preBackupExit = Artisan::call('snipeit:backup'")
        end = source.index(']);', start)
        before, calltext, after = source[:start], source[start:end], source[end:]
        needle = "'--with-remote-files' => true,"
        if calltext.count(needle) != 1:
            raise RuntimeError('FR-9 mutation target is ambiguous')
        mutation = subprocess.run(['sed', "s/'--with-remote-files' => true,//"],
                                  input=calltext, text=True, stdout=subprocess.PIPE, check=True).stdout
        if needle in mutation:
            raise RuntimeError('FR-9 mutation did not remove the target')
        controller.write_text(before + mutation + after)
        cached_dockerfile(mutated)
        mut_id = build(mutated, RUN + ':mutated', cache)
        mut_test = test_image(context, mut_id, vendor, RUN + ':mutated-test')
        php_identity(mut_id, mut_test)
        phpunit(mut_test, ['--filter', 'web_restore_calls_the_safety_backup_with_remote_files_before_wiping',
                           'tests/Feature/S3Compatibility/WebRestoreValidatesBeforeWipeTest.php'],
                common, 'fr9-mutation.xml', 'fr9_mutation')

try:
    main()
except Exception as e:
    # Exception messages here contain operational metadata only, never command output.
    data['errors'].append(str(e).replace(secret, '[redacted]').replace(dbpass, '[redacted]'))
finally:
    for name in reversed(CONTAINERS):
        docker('rm', '-f', '-v', name, check=False)
    for name in reversed(VOLUMES):
        docker('volume', 'rm', name, check=False)
    for name in reversed(NETWORKS):
        docker('network', 'rm', name, check=False)
    for name in reversed(IMAGES):
        docker('image', 'rm', name, check=False)
    counts = {}
    for case in data['tests']:
        counts[case['status']] = counts.get(case['status'], 0) + 1
    data['counts'] = counts
    if ROUND == 'A':
        mutations = [case for case in data['tests'] if case['run'] == 'fr9_mutation']
        data['probes']['fr9_mutation_red'] = {
            'passed': any(case['status'] == 'failure' for case in mutations),
            'tests_found': len(mutations),
        }
        if not mutations:
            data['errors'].append('FR-9 mutation produced no test result')
    elif counts.get('failure', 0) or counts.get('error', 0) or counts.get('skipped', 0):
        data['errors'].append('required tests failed or were skipped')
    if ROUND != 'A':
        for key, result in data['probes'].items():
            if isinstance(result, dict) and result.get('passed') is False:
                data['errors'].append(key + ' probe failed')
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2) + '\n')
    shutil.rmtree(TMP)
sys.exit(1 if data['errors'] else 0)