"""Disposable test stack on an internal Docker network (no egress, no published ports).

Creates: <prefix>-net (internal), <prefix>-db (mysql:8.4), optional <prefix>-s3 (S3 mock),
optional <prefix>-smtp (SMTP fixture), and <prefix>-app (the image under test) with the
production security options. Everything is removed by Stack.down().
"""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP_KEY = 'base64:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
ENV = dict(os.environ, MSYS_NO_PATHCONV='1')
# Platform of the image under test (e.g. linux/arm64 under emulation); helpers stay native.
PLATFORM_ARGS = ['--platform', os.environ['OPCACHE_PLATFORM']] if os.environ.get('OPCACHE_PLATFORM') else []


def docker(*args, check=True, capture=True, timeout=600):
    result = subprocess.run(['docker', *args], text=True, encoding='utf-8', errors='replace', env=ENV,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None, timeout=timeout)
    if check and result.returncode != 0:
        raise RuntimeError(f'docker {" ".join(args[:3])} failed: {result.stdout[-2000:] if result.stdout else ""}')
    return result


def host_path(path):
    """Docker Desktop on Windows accepts native paths for bind mounts."""
    return str(Path(path).resolve())


class Stack:
    def __init__(self, image, prefix=None, s3=False, smtp=False, mounts=(), mem_limit=None):
        self.image = image
        self.prefix = prefix or 'opc-' + uuid.uuid4().hex[:8]
        self.net = self.prefix + '-net'
        self.db = self.prefix + '-db'
        self.app = self.prefix + '-app'
        self.s3 = self.prefix + '-s3' if s3 else None
        self.smtp = self.prefix + '-smtp' if smtp else None
        self.mounts = list(mounts)
        self.mem_limit = mem_limit
        self.created = []

    # -- lifecycle ---------------------------------------------------------
    def up(self, timeout=int(os.environ.get('OPCACHE_STACK_TIMEOUT', '420'))):
        docker('network', 'create', '--internal', self.net)
        self.created.append(('network', self.net))
        if json.loads(docker('network', 'inspect', self.net).stdout)[0]['Internal'] is not True:
            raise RuntimeError('test network is not internal')
        self._run(self.db, ['-e', 'MYSQL_ROOT_PASSWORD=root-test', '-e', 'MYSQL_DATABASE=snipeit',
                            '-e', 'MYSQL_USER=snipeit', '-e', 'MYSQL_PASSWORD=snipeit-test'], 'mysql:8.4')
        if self.s3:
            self._run(self.s3, ['-v', host_path(ROOT / 's3mock/server.py') + ':/app/server.py:ro'],
                      'python:3.12-slim', ['python', '-u', '/app/server.py'])
        if self.smtp:
            self._run(self.smtp, ['-v', host_path(ROOT / 'verification/compatibility-closure/smtp-fixture.py')
                                  + ':/f.py:ro'], 'python:3.12-slim', ['python', '-u', '/f.py'])
        self._wait(lambda: docker('exec', self.db, 'mysqladmin', 'ping', '-h127.0.0.1', '-usnipeit',
                                  '-psnipeit-test', '--silent', check=False).returncode == 0, timeout, 'mysql')
        env = ['-e', 'APP_KEY=' + APP_KEY, '-e', f'APP_URL=http://{self.app}:8080', '-e', 'APP_ENV=production',
               '-e', 'APP_DEBUG=false', '-e', 'DB_CONNECTION=mysql', '-e', 'DB_HOST=' + self.db,
               '-e', 'DB_PORT=3306', '-e', 'DB_DATABASE=snipeit', '-e', 'DB_USERNAME=snipeit',
               '-e', 'DB_PASSWORD=snipeit-test', '-e', 'DB_DUMP_PATH=/usr/bin', '-e', 'CACHE_DRIVER=file',
               '-e', 'SESSION_DRIVER=file', '-e', 'QUEUE_CONNECTION=sync']
        if self.smtp:
            env += ['-e', 'MAIL_MAILER=smtp', '-e', 'MAIL_HOST=' + self.smtp, '-e', 'MAIL_PORT=1025',
                    '-e', 'MAIL_ENCRYPTION=null', '-e', 'MAIL_FROM_ADDR=test@example.invalid',
                    '-e', 'MAIL_FROM_NAME=Test', '-e', 'MAIL_REPLYTO_ADDR=test@example.invalid',
                    '-e', 'MAIL_REPLYTO_NAME=Test']
        else:
            env += ['-e', 'MAIL_MAILER=log']
        if self.s3:
            for side, bucket in (('PUBLIC', 'snipeit-public'), ('PRIVATE', 'snipeit-private')):
                env += ['-e', f'{side}_FILESYSTEM_DISK=s3_{side.lower()}', '-e', f'{side}_AWS_ACCESS_KEY_ID=test-access',
                        '-e', f'{side}_AWS_SECRET_ACCESS_KEY=test-secret', '-e', f'{side}_AWS_DEFAULT_REGION=us-east-1',
                        '-e', f'{side}_AWS_BUCKET={bucket}', '-e', f'{side}_AWS_ENDPOINT=http://{self.s3}:9000',
                        '-e', f'{side}_AWS_PATH_STYLE=true']
            env += ['-e', 'PUBLIC_S3_PROXY=true']
        opts = ['--user', '10000:50', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true'] + env
        if self.mem_limit:
            opts += ['--memory', self.mem_limit]
        for source, target in self.mounts:
            opts += ['-v', f'{host_path(source)}:{target}:ro']
        self._run(self.app, PLATFORM_ARGS + opts, self.image)
        self._wait(self.healthy, timeout, 'app /health')
        return self

    def down(self):
        for kind, name in reversed(self.created):
            if kind == 'container':
                docker('rm', '-f', '-v', name, check=False)
            else:
                docker('network', 'rm', name, check=False)
        self.created.clear()

    def __enter__(self):
        try:
            return self.up()
        except BaseException:
            self.logs_on_failure = self.logs()
            self.down()
            raise

    def __exit__(self, *exc):
        self.down()

    # -- helpers -----------------------------------------------------------
    def _run(self, name, opts, image, command=()):
        docker('run', '-d', '--name', name, '--network', self.net, *opts, image, *command)
        self.created.append(('container', name))

    def _wait(self, predicate, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            if self.app in [n for k, n in self.created if k == 'container'] and not self.running(self.app):
                raise RuntimeError(f'{self.app} exited while waiting for {what}:\n' + self.logs()[-3000:])
            time.sleep(3)
        raise RuntimeError(f'timeout waiting for {what}')

    def running(self, name):
        result = docker('inspect', '-f', '{{.State.Running}}', name, check=False)
        return result.stdout.strip() == 'true'

    def php(self, code, check=True):
        return docker('exec', self.app, '/usr/bin/php', '-r', code, check=check)

    def http(self, path):
        code = ('$c=stream_context_create(["http"=>["ignore_errors"=>true,"timeout"=>15]]);'
                f'$b=@file_get_contents("http://127.0.0.1:8080{path}",false,$c);'
                'echo json_encode(["status"=>$http_response_header[0]??null,"body"=>$b]);')
        return json.loads(self.php(code).stdout)

    def healthy(self):
        if not self.running(self.app):
            return False
        try:
            return json.loads(self.http('/health')['body'] or '{}').get('status') == 'ok'
        except (RuntimeError, ValueError):
            return False

    def logs(self):
        return docker('logs', self.app, check=False).stdout or ''
