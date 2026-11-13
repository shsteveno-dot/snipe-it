#!/usr/bin/env python3
"""Cloud-only review-fixes runner. Results contain no command output or env."""
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
from urllib.parse import urlparse
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
PINNED = {}
CACHE_ROOT = Path(os.environ.get('REVIEW_FIXES_CACHE_DIR', str(Path.home() / '.cache' / 'review-fixes'))).expanduser()
MIRRORS = CACHE_ROOT / 'mirrors'
DEBUG_LOG = CACHE_ROOT / ('runner-debug-' + ROUND + '.log')
PROXY_CA = Path(os.environ.get('REVIEW_PROXY_CA', '/root/.ccr/agent-proxy-ca.crt')).expanduser()
PROXY_CONTEXT = TMP / 'proxy-ca'
GOPEAR_CONTEXT = TMP / 'go-pear'
secret = base64.b64encode(os.urandom(32)).decode()
appkey = 'base64:' + secret
dbpass = uuid.uuid4().hex
data = {'round': ROUND, 'run_id': RUN, 'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'commit': None, 'platform': platform.platform(), 'target_platform': 'linux/amd64', 'candidate_image_id': None, 'test_image_id': None,
        'php_comparison': {}, 'tests': [], 'counts': {}, 'probes': {}, 'commands': [], 'skipped_summary': {}, 'errors': []}

def redact_output(output):
    for value in (appkey, secret, dbpass, os.environ.get('HTTPS_PROXY', ''), os.environ.get('HTTP_PROXY', ''), os.environ.get('https_proxy', ''), os.environ.get('http_proxy', '')):
        if value:
            output = output.replace(value, '[redacted]')
    cleaned = []
    for line in output.splitlines():
        if re.search(r'(?i)(password|passwd|secret|token|authorization|private.key|credential|app.key|api.key|access.key)', line):
            cleaned.append('[redacted sensitive line]')
        else:
            cleaned.append(re.sub(r'(https?://)[^/\s]*@', r'\1[redacted]@', line))
    return '\n'.join(cleaned)

def call(args, check=True, cwd=None, env=None):
    # Persist commands and exit codes, while removing generated secrets and URL credentials.
    recorded = []
    for arg in args:
        value = str(arg).replace(appkey, '[redacted]').replace(secret, '[redacted]').replace(dbpass, '[redacted]')
        value = re.sub(r'(?i)^([^=]*(?:password|passwd|secret|token|authorization|credential|api.key|access.key)[^=]*=).*$', r'\1[redacted]', value)
        if '://' in value and ('@' in value or '?' in value):
            value = '[redacted-url]'
        recorded.append(value)
    p = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    data['commands'].append({'argv': recorded, 'exit_code': p.returncode})
    DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(DEBUG_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as log:
        log.write('\n### exit=' + str(p.returncode) + ' ' + ' '.join(recorded) + '\n')
        log.write(redact_output(p.stdout or '')[-20000:] + '\n')
    if check and p.returncode:
        raise RuntimeError('command failed: ' + ' '.join(args[:2]) + ' (exit ' + str(p.returncode) + ')')
    return p

def docker(*args, check=True):
    return call(['docker', *map(str, args)], check=check)

def cleanup_previous_runs():
    # Only resources explicitly bearing this feature's run label are touched.
    for kind, list_args, remove_args in [
        ('containers', ['ps', '-aq', '--filter', 'label=review-fixes.run'], ['rm', '-f', '-v']),
        ('volumes', ['volume', 'ls', '-q', '--filter', 'label=review-fixes.run'], ['volume', 'rm']),
        ('networks', ['network', 'ls', '-q', '--filter', 'label=review-fixes.run'], ['network', 'rm']),
    ]:
        found = docker(*list_args).stdout.split()
        for item in dict.fromkeys(found):
            result = docker(*remove_args, item, check=False)
            if result.returncode:
                raise RuntimeError('could not remove labelled leftover ' + kind)
    # The same image ID can have several tags, so remove labelled tags before
    # considering dangling IDs; deleting by ID alone fails for multi-tag images.
    listing = docker('image', 'ls', '--filter', 'label=review-fixes.run',
                     '--format', '{{.Repository}}:{{.Tag}} {{.ID}}').stdout.splitlines()
    references = []
    for line in listing:
        tag, image_id = line.split(None, 1)
        references.append(image_id if tag == '<none>:<none>' else tag)
    for reference in dict.fromkeys(references):
        if docker('image', 'inspect', reference, check=False).returncode == 0:
            if docker('image', 'rm', reference, check=False).returncode:
                raise RuntimeError('could not remove labelled leftover image')

def pull_with_backoff(reference):
    if docker('image', 'inspect', reference, check=False).returncode == 0:
        return
    for attempt in range(5):
        result = docker('pull', '--platform', 'linux/amd64', reference, check=False)
        if result.returncode == 0:
            return
        if attempt < 4:
            time.sleep(5 * (2 ** attempt))
    raise RuntimeError('failed to pull base image after retries: ' + reference)

def prepare_base_images(context):
    images = {
        'docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e',
        'docker.io/library/golang@sha256:672c944cfd07599b5f1bb179869270cdc94c6254e41db4d431259693cb286b82',
        'docker.io/library/composer:2.10.3@sha256:af98f42dfff7c68ba8d53c2164fd9fde1087b7d449514baa38c418b1f6bc4bac',
        'docker.io/library/ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55',
        'composer:2.10.3', 'composer:latest', 'ubuntu:24.04', 'mysql:8.4',
    }
    for image in sorted(images):
        pull_with_backoff(image)
        # Mutable tags used by the upstream Dockerfile are resolved and pulled by digest too.
        if '@sha256:' not in image:
            p = docker('image', 'inspect', '--format', '{{index .RepoDigests 0}}', image, check=False)
            digest = p.stdout.strip()
            if p.returncode or '@sha256:' not in digest:
                raise RuntimeError('base image has no repository digest: ' + image)
            pull_with_backoff(digest)

def prepare_build_contexts():
    if os.environ.get('REVIEW_PROXY_CA') and not PROXY_CA.is_file():
        raise RuntimeError('REVIEW_PROXY_CA does not name a readable file')
    if PROXY_CA.is_file():
        PROXY_CONTEXT.mkdir()
        shutil.copyfile(PROXY_CA, PROXY_CONTEXT / 'agent-proxy-ca.crt')
    GOPEAR_CONTEXT.mkdir()
    MIRRORS.mkdir(parents=True, exist_ok=True)
    pear = MIRRORS / 'pearweb_phars.git'
    if not pear.exists():
        call(['git', 'clone', '--mirror', '--filter=blob:none', 'https://github.com/pear/pearweb_phars.git', str(pear)])
    if call(['git', '--git-dir', str(pear), 'cat-file', '-e', '72aa5f771f^{commit}'], check=False).returncode:
        call(['git', '--git-dir', str(pear), 'fetch', 'origin', '72aa5f771f'])
    with (GOPEAR_CONTEXT / 'go-pear.phar').open('wb') as out:
        subprocess.run(['git', '--git-dir', str(pear), 'show', '72aa5f771f:go-pear.phar'], stdout=out, check=True)

def image_id(tag):
    return docker('image', 'inspect', '--format', '{{.Id}}', tag).stdout.strip()

def make_context(dest):
    dest.mkdir()
    archive = TMP / (dest.name + '.tar')
    with archive.open('wb') as out:
        subprocess.run(['git', '-C', str(ROOT), 'archive', 'HEAD'], stdout=out, check=True)
    with tarfile.open(archive) as tf:
        # The archive is produced by the current checkout, not an untrusted ZIP.
        tf.extractall(dest, filter='data')

def prepare_cache(context):
    cache = TMP / 'composer-cache'
    cache.mkdir()
    MIRRORS.mkdir(parents=True, exist_ok=True)
    lock = json.loads((context / 'composer.lock').read_text())
    for pkg in lock['packages'] + lock['packages-dev']:
        dist, source = pkg.get('dist', {}), pkg.get('source', {})
        url = dist.get('url', '')
        if not (url.startswith('https://api.github.com/') or url.startswith('https://codeload.github.com/')):
            continue
        source_url = source.get('url')
        if not source_url:
            parsed = urlparse(url)
            parts = parsed.path.strip('/').split('/')
            if parsed.hostname == 'api.github.com' and len(parts) >= 3 and parts[0] == 'repos':
                source_url = 'https://github.com/' + '/'.join(parts[1:3]) + '.git'
            elif parsed.hostname == 'codeload.github.com' and len(parts) >= 2:
                source_url = 'https://github.com/' + '/'.join(parts[:2]) + '.git'
        ref = dist.get('reference') or source.get('reference')
        if not source_url or not ref:
            raise RuntimeError('locked package lacks source/reference: ' + pkg['name'])
        if source_url.startswith('git@github.com:'):
            source_url = 'https://github.com/' + source_url.split(':', 1)[1]
        mirror = MIRRORS / ('git-' + hashlib.sha256(source_url.encode()).hexdigest())
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
    if PROXY_CA.is_file():
        ca_needle = 'COPY docker/chiseled/ /chisel-inputs/'
        if ca_needle not in text:
            raise RuntimeError('proxy CA insertion point not found')
        text = text.replace(ca_needle, 'COPY --from=proxyca agent-proxy-ca.crt /usr/local/share/ca-certificates/agent-proxy-ca.crt\nRUN update-ca-certificates\n' + ca_needle, 1)
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
        if PROXY_CA.is_file():
            args += ['--build-context', 'proxyca=' + str(PROXY_CONTEXT)]
    elif dockerfile == 'Dockerfile':
        regular_dockerfile(context)
        args += ['--build-context', 'composercache=' + str(cache), '--build-context', 'gopear=' + str(GOPEAR_CONTEXT)]
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
    built = image_id(tag)
    PINNED[built] = tag + '@' + built
    return built

def regular_dockerfile(context):
    # Network-only substitutions in the throwaway context; COPY . and ignore rules stay intact.
    path = context / 'Dockerfile'
    text = path.read_text()
    pear = 'RUN curl -L -O https://github.com/pear/pearweb_phars/raw/master/go-pear.phar'
    composer = 'RUN COMPOSER_CACHE_DIR=/dev/null composer install --no-dev --working-dir=/var/www/html'
    if pear not in text or composer not in text:
        raise RuntimeError('regular Dockerfile insertion points not found')
    text = text.replace(pear, 'COPY --from=gopear go-pear.phar /go-pear.phar', 1)
    text = text.replace(composer, 'COPY --from=composercache --chown=10000:50 / /tmp/composer-cache/\nRUN COMPOSER_CACHE_DIR=/tmp/composer-cache composer install --no-dev --working-dir=/var/www/html', 1)
    path.write_text(text)

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
           '--build-arg', 'CANDIDATE=' + PINNED[candidate], '--build-context', 'devvendor=' + str(vendor),
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

def round_a_expectation(name, label):
    if label == 'fr9_mutation':
        return 'red', 'Finding 9: safety backup omitted remote files.'
    red = [
        ('test_login_endpoint_does_not_fall_back_to_synced_password_after_ou_rejection', 'The user is authenticated'),
        ('test_dn_separator_after_even_backslashes_cannot_skip_a_deselected_ou', 'Failed asserting that true is false'),
        ('test_finding5_odd_backslashes_and_escaped_hex_preserve_parent_ou', 'Failed asserting that false is true'),
        ('test_ou_search_rejects_a_partial_limited_result', 'exception of type'),
        ('import_locations_rejects_a_truncated_remote_csv_before_importing', 'Expected status code 1 but received 0'),
        ('local_destination_prefers_manifest_staged_copy_when_stale_copy_follows', 'Failed asserting that two strings are identical'),
        ('validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped', 'backup file passed validation'),
        ('finding4_web_restore_rejects_a_corrupted_stale_entry_before_wipe', 'Finding 4: CRC entry was not reported before wipe.'),
    ]
    for fragment, message in red:
        if fragment in name:
            return 'red', message
    if 'test_finding6_ou_search_preserves_selection' in name and 'complete paginated' not in name:
        return 'red', "matches expected 'error'"
    if 'finding7_remote_copy_and_size_failures' in name and 'unavailable size' in name:
        return 'red', 'Expected status code 1 but received 0'
    if 'finding3_restore_destination_prefers_staged' in name and 'stale last' in name and 'control' not in name:
        return 'red', 'Failed asserting that two strings are identical'
    controls = (
        'test_finding1_local_non_ldap_user_can_still_log_in',
        'finding3_restore_destination_prefers_staged',
        'finding4_validate_only_rejects_a_broken_central_directory',
        'finding4_validate_only_checks_manifest_size_and_sha256',
        'validate_only_rejects_a_truncated_zip_without_changing_the_database',
        'finding7_remote_copy_and_size_failures',
        'test_finding6_ou_search_preserves_selection',
        'web_restore_calls_the_safety_backup_with_remote_files_before_wiping',
    )
    return ('control', '') if any(fragment in name for fragment in controls) else ('existing', '')

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
        name = case.get('name', '')
        lines = [line.strip() for line in lines if line.strip()]
        if lines and '::' in lines[0] and name.split(' with data set')[0] in lines[0]:
            lines.pop(0)
        message = redact_output(lines[0]) if lines else ''
        for value in (secret, appkey, dbpass):
            message = message.replace(value, '[redacted]')
        status = 'passed' if child is None else child.tag
        expectation, reason = round_a_expectation(name, label)
        expected_status = 'failure' if label == 'fr9_mutation' or (ROUND == 'A' and expectation == 'red') else 'passed'
        matched = status == expected_status
        if matched and expectation == 'red' and (ROUND == 'A' or label == 'fr9_mutation') and reason:
            matched = reason.lower() in message.lower()
        data['tests'].append({'run': label, 'name': case.get('classname', '') + '::' + name,
                              'status': status, 'message': message[:500],
                              'round_a_expectation': expectation, 'expected_status': expected_status,
                              'matches_expectation': matched})
        if status == 'error':
            data['errors'].append(label + ': JUnit error in ' + name)
        elif not matched:
            data['errors'].append(label + ': unexpected result in ' + name)

def phpunit(test, args, extra, file, label):
    p = run_php(test, '/var/www/html/vendor/bin/phpunit', '--colors=never', '--display-skipped',
                '--log-junit', '/results/' + file, *args, extra=extra)
    data['probes'][label + '_exit'] = p.returncode
    if p.returncode == 2 or p.returncode > 2:
        data['errors'].append(label + ': phpunit exited ' + str(p.returncode))
    lines = (p.stdout or '').splitlines()
    start = next((i for i, line in enumerate(lines) if re.search(r'(?i)there (?:was|were) .*skipped', line)), None)
    data['skipped_summary'][label] = redact_output('\n'.join(lines[start:start + 35]))[:4000] if start is not None else ''
    parse_junit(TMP / 'results' / file, label)
    return p.returncode

def probe_status(name, process):
    passed = process.returncode == 0
    should_pass = ROUND != 'A' or name not in ('fr2_chiseled', 'fr2_regular', 'fr8_valid')
    matched = passed if should_pass else process.returncode == 1
    data['probes'][name] = {'exit_code': process.returncode, 'passed': passed,
                            'expected_status': 'pass' if should_pass else 'red',
                            'matches_expectation': matched}
    if not matched:
        data['errors'].append(name + ': unexpected probe result')

def main():
    data['commit'] = call(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).stdout.strip()
    if call(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=no', '--', '.', ':(exclude)cloud-verify/review-fixes/results-*.json']).stdout.strip():
        raise RuntimeError('checkout must be clean before starting')
    lock_check = call(['python3', '-I', 'docker/chiseled/repin_app_inputs.py', '--check'], cwd=ROOT, check=False)
    data['probes']['chiseled_input_locks'] = {'passed': lock_check.returncode == 0, 'exit_code': lock_check.returncode}
    if lock_check.returncode:
        raise RuntimeError('Chiseled input lock check failed; see debug log')
    # Never remove another live invocation's labelled resources.
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    global RUN_LOCK
    RUN_LOCK = (CACHE_ROOT / 'runner.lock').open('a')
    try:
        fcntl.flock(RUN_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('another review-fixes runner holds the cloud lock')
    cleanup_previous_runs()
    context = TMP / 'context'
    make_context(context)
    prepare_build_contexts()
    prepare_base_images(context)
    cache = prepare_cache(context)
    vendor = make_vendor(context, cache)
    cached_dockerfile(context)
    candidate_tag = RUN + ':candidate'
    candidate = build(context, candidate_tag, cache)
    data['candidate_image_id'] = candidate
    if PROXY_CA.is_file():
        check = (
            "$pem=file_get_contents('/probe/proxy-ca.crt');"
            "$bundle=@file_get_contents('/etc/ssl/certs/ca-certificates.crt');"
            "if($pem===false || strlen($pem)===0 || $bundle===false){exit(2);}"
            "if(file_exists('/usr/local/share/ca-certificates/agent-proxy-ca.crt')"
            "||file_exists('/etc/ssl/certs/agent-proxy-ca.pem')"
            "||($bundle!==false && strpos($bundle,$pem)!==false)){exit(1);}"
        )
        result = run_php(candidate, '-r', check, extra=['-v', str(PROXY_CONTEXT / 'agent-proxy-ca.crt') + ':/probe/proxy-ca.crt:ro'])
        probe_status('candidate_proxy_ca_absent', result)
        if result.returncode != 0:
            raise RuntimeError('proxy CA reached candidate image or CA check could not run')
    test = test_image(context, candidate, vendor, RUN + ':test')
    data['test_image_id'] = test
    php_identity(candidate, test)
    if ROUND != 'A':
        # Build the test executable with the same pinned Go toolchain as the
        # candidate, then execute the assertion inside its Chiseled descendant.
        go_output = TMP / 'go-test'
        go_output.mkdir(mode=0o777)
        go_output.chmod(0o777)
        go_image = 'docker.io/library/golang@sha256:672c944cfd07599b5f1bb179869270cdc94c6254e41db4d431259693cb286b82'
        docker('run', '--rm', '--label', LABEL, '--network', 'none',
               '-v', str(context / 'docker/snipeit-runtime') + ':/src:ro',
               '-v', str(go_output) + ':/out', '-w', '/src', '-e', 'CGO_ENABLED=0',
               go_image, 'go', 'test', '-c', '-o', '/out/startup.test', './internal/startup')
        go_test = docker('run', '--rm', '--label', LABEL, '--network', 'none',
                         '-v', str(go_output / 'startup.test') + ':/probe/startup.test:ro',
                         '--entrypoint', '/probe/startup.test', test,
                         '-test.run=^TestForwardedHeaderConfig$', '-test.v', check=False)
        probe_status('fr8_go_unit', go_test)
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
    fixture_passed = cp.returncode != 0
    fixture_matched = fixture_passed if ROUND != 'A' else not fixture_passed
    data['probes']['fr2_prepare_app'] = {'passed': fixture_passed, 'marker_directory_present': not fixture_passed,
                                         'expected_status': 'red' if ROUND == 'A' else 'pass',
                                         'matches_expectation': fixture_matched}
    if not fixture_matched:
        data['errors'].append('fr2_prepare_app: unexpected probe result')

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
            invalid_passed = state == 'false' and code != '0'
            invalid_matched = invalid_passed if ROUND != 'A' else state == 'true'
            data['probes']['fr8_invalid'] = {'passed': invalid_passed, 'running': state == 'true',
                                             'exit_code': int(code), 'expected_status': 'red' if ROUND == 'A' else 'pass',
                                             'matches_expectation': invalid_matched}
            if not invalid_matched:
                data['errors'].append('fr8_invalid: unexpected probe result')
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

    if ROUND in ('A', 'B', 'final'):
        fr9_filter = 'web_restore_calls_the_safety_backup_with_remote_files_before_wiping'
        baseline_exit = phpunit(test, ['--filter', fr9_filter,
                                      'tests/Feature/S3Compatibility/WebRestoreValidatesBeforeWipeTest.php'],
                                common, 'fr9-original.xml', 'fr9_original')
        baseline = [case for case in data['tests'] if case['run'] == 'fr9_original']
        if baseline_exit != 0 or len(baseline) != 1 or baseline[0]['status'] != 'passed':
            raise RuntimeError('FR-9 unmutated endpoint test did not pass')
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
    if ROUND in ('A', 'B', 'final'):
        mutations = [case for case in data['tests'] if case['run'] == 'fr9_mutation']
        data['probes']['fr9_mutation_red'] = {
            'passed': len(mutations) == 1 and mutations[0]['matches_expectation'],
            'tests_found': len(mutations),
        }
        if not mutations:
            data['errors'].append('FR-9 mutation produced no test result')
        elif not data['probes']['fr9_mutation_red']['passed']:
            data['errors'].append('FR-9 mutation did not fail for the expected assertion')
    if ROUND != 'A' and any(case['status'] != 'passed' for case in data['tests'] if case['run'] != 'fr9_mutation'):
        data['errors'].append('required tests failed or were skipped')
    if ROUND != 'A':
        for key, result in data['probes'].items():
            if isinstance(result, dict) and result.get('passed') is False:
                data['errors'].append(key + ' probe failed')
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2) + '\n')
    shutil.rmtree(TMP)
sys.exit(1 if data['errors'] else 0)
