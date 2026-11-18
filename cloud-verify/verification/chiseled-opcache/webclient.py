"""HTTP client run inside a python:3.12-slim container on the internal test network (stdlib only).

python webclient.py setup <base> <username> <password>
python webclient.py bench <base> <username> <password> <warmup> <count>
Prints one JSON object. Any non-2xx response or failed login aborts with exit 1.
"""
import html.parser
import http.cookiejar
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request


class TokenParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == '_token':
            self.token = attrs.get('value')


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        with self.opener.open(urllib.request.Request(self.base + path, data=body), timeout=60) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f'{path}: HTTP {response.status}')
            return response.geturl(), response.read().decode('utf-8', 'replace')

    def token(self, path):
        _, page = self.request(path)
        parser = TokenParser()
        parser.feed(page)
        if not parser.token:
            raise RuntimeError('no CSRF token on ' + path)
        return parser.token

    def login(self, username, password):
        token = self.token('/login')
        url, page = self.request('/login', {'_token': token, 'username': username, 'password': password})
        if url.rstrip('/').endswith('/login') or 'name="password"' in page:
            raise RuntimeError('login failed')
        return url


def setup(base, username, password):
    client = Client(base)
    token = client.token('/setup/user')
    url, _ = client.request('/setup/user', {
        '_token': token, 'site_name': 'OPcache regression', 'first_name': 'Test', 'last_name': 'Admin',
        'email': username + '@example.invalid', 'username': username, 'password': password,
        'password_confirmation': password, 'locale': 'en-US', 'default_currency': 'USD',
        'auto_increment_prefix': '', 'zerofill_count': '5'})
    after_setup = url
    client = Client(base)
    landing = client.login(username, password)
    _, dashboard = client.request('/')
    return {'setup_redirect': after_setup, 'login_landing': landing,
            'dashboard_ok': 'Dashboard' in dashboard or 'dashboard' in dashboard}


def bench(base, username, password, warmup, count):
    client = Client(base)
    client.login(username, password)
    result = {}
    for path in ('/health', '/'):
        for _ in range(warmup):
            client.request(path)
        samples = []
        for _ in range(count):
            start = time.perf_counter()
            client.request(path)
            samples.append((time.perf_counter() - start) * 1000)
        ordered = sorted(samples)
        result[path] = {'count': count, 'p50_ms': statistics.median(samples),
                        'p95_ms': ordered[max(0, int(round(0.95 * count)) - 1)], 'samples_ms': samples}
    return result


if __name__ == '__main__':
    mode, base, username, password = sys.argv[1:5]
    try:
        if mode == 'setup':
            output = setup(base, username, password)
        else:
            output = bench(base, username, password, int(sys.argv[5]), int(sys.argv[6]))
    except Exception as error:  # report and fail closed
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}))
        sys.exit(1)
    print(json.dumps(output))
