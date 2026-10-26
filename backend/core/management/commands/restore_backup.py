"""`manage.py restore_backup <file> --confirm` — puts a backup back.

This REPLACES the current database with the backup's contents. Stop the
app first (systemctl stop shop-gunicorn), restore, then start it.
A copy of the current database is taken first, so a restore of the wrong
file can itself be undone.

Practise it: restore last night's backup onto a test machine (or a copy
of .env pointing at a scratch database) every few months. A backup that
has never been restored is a hope, not a backup.
"""

import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from .backup import db_engine, pg_env, verify_postgres, verify_sqlite


class Command(BaseCommand):
    help = 'Replace the current database (and media, with --media) with a backup made by `manage.py backup`.'

    def add_arguments(self, parser):
        parser.add_argument('file', help='shop-YYYYMMDD-HHMMSS.dump or .sqlite3')
        parser.add_argument('--media', default=None, help='Also restore uploaded files from this -media.tar.gz.')
        parser.add_argument('--confirm', action='store_true', help='Required: you understand the database is replaced.')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'No such file: {path}')
        if not options['confirm']:
            raise CommandError('This replaces the current database. Stop the app, then re-run with --confirm.')

        # Safety net: back up what's there now before overwriting it.
        safety_dir = Path(settings.BACKUP_DIR or path.parent) / 'before-restore'
        call_command('backup', dir=str(safety_dir), keep=5, stdout=self.stdout)

        if db_engine() == 'sqlite':
            verify_sqlite(path)
            connections.close_all()
            target = Path(settings.DATABASES['default']['NAME'])
            shutil.copyfile(path, target)
        else:
            verify_postgres(path)
            env, conn_args, name = pg_env()
            subprocess.run(['pg_restore', '--clean', '--if-exists', '--no-owner', '--single-transaction',
                            '--dbname', name, *conn_args, str(path)], env=env, check=True)

        if options['media']:
            media_root = Path(settings.MEDIA_ROOT)
            if media_root.exists():
                media_root.rename(media_root.with_name(f'media-before-restore-{datetime.now():%Y%m%d%H%M%S}'))
            with tarfile.open(options['media']) as tar:
                tar.extractall(media_root.parent, filter='data')

        call_command('migrate', interactive=False, verbosity=0)
        self.stdout.write(self.style.SUCCESS(
            f'Restored {path.name}. The previous database was saved in {safety_dir}. Start the app again.'))
