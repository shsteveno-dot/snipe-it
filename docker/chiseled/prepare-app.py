#!/usr/bin/env python3
"""Project application assembly: the layout of the application tree inside the image."""
import os
from pathlib import Path
import shutil

app = Path('/var/www/html')
links = {'storage/private_uploads': '/var/lib/snipeit/data/private_uploads',
         'public/uploads': '/var/lib/snipeit/data/uploads',
         'storage/app/backups': '/var/lib/snipeit/dumps',
         'storage/oauth-private.key': '/var/lib/snipeit/keys/oauth-private.key',
         'storage/oauth-public.key': '/var/lib/snipeit/keys/oauth-public.key',
         'storage/ldap_client_tls.cert': '/var/lib/snipeit/keys/ldap_client_tls.cert',
         'storage/ldap_client_tls.key': '/var/lib/snipeit/keys/ldap_client_tls.key'}
for relative, target in links.items():
    path = app / relative
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
for name in ('docker', '.git', '.github', '.agents', '.codex', '.spec', 'tests', '.ai', '.claude', 'cloud-verify',
             '.phpunit.cache', 'storage/framework/testing', 'storage/app/backup-temp',
             'storage/framework/backup-staging'):
    path = app / name
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
for pattern in ('Dockerfile*', 'docker-compose*', '.dockerignore', '.env.testing', '.env.dusk.local',
                '.phpunit.result.cache', 'CLOUD_TEST*.md', 'cloud-test-output.txt'):
    for path in app.glob(pattern):
        if path.is_file():
            path.unlink()
# Files a developer's checkout generates at run time: logs, compiled views, sessions, caches. A build from a
# working directory would otherwise ship them; the directories and their .gitignore placeholders stay.
for directory in ('storage/logs', 'storage/framework/views', 'storage/framework/sessions',
                  'storage/framework/cache/data', 'bootstrap/cache'):
    root = app / directory
    if not root.is_dir():
        continue
    for path in list(root.iterdir()):
        if path.name in ('.gitignore', '.gitkeep'):
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
(app / 'artisan').chmod(0o755)
for path in [app, *app.rglob('*')]:
    os.chown(path, 10000, 50, follow_symlinks=False)
for path in ('/tmp/composer-cache', '/tmp/composer-home'):  # nosec B108
    Path(path).mkdir(exist_ok=True)
    os.chown(path, 10000, 50)
