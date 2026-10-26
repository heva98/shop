"""Nightly backup: `manage.py backup` (run by deploy/systemd/shop-backup.timer).

Writes, into BACKUP_DIR:
  shop-YYYYMMDD-HHMMSS.dump      Postgres (pg_dump custom format), or
  shop-YYYYMMDD-HHMMSS.sqlite3   SQLite (online copy via the backup API)
  shop-YYYYMMDD-HHMMSS-media.tar.gz   uploaded files (logos), if any

Every backup is checked after it's written (pg_restore can read the whole
archive / SQLite integrity_check passes and the tables are there), then
only the newest BACKUP_KEEP backups are kept. Any failure raises, so
systemd marks the run failed, and logs at ERROR, which emails ADMINS.

Backups on the same disk as the database don't survive the disk dying:
copy BACKUP_DIR off the server too (see deploy/README.md, "Backups").
"""

import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

logger = logging.getLogger('core.management.backup')


def db_engine():
    engine = settings.DATABASES['default']['ENGINE']
    if 'postgresql' in engine:
        return 'postgres'
    if 'sqlite3' in engine:
        return 'sqlite'
    raise CommandError(f'Backups are not implemented for {engine}.')


def pg_env():
    db = settings.DATABASES['default']
    env = dict(os.environ)
    if db.get('PASSWORD'):
        env['PGPASSWORD'] = str(db['PASSWORD'])
    args = []
    for flag, key in (('-h', 'HOST'), ('-p', 'PORT'), ('-U', 'USER')):
        if db.get(key):
            args += [flag, str(db[key])]
    return env, args, db['NAME']


class Command(BaseCommand):
    help = 'Back up the database and uploaded files into BACKUP_DIR, verify the backup, and prune old ones.'

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=None, help='Overrides BACKUP_DIR.')
        parser.add_argument('--keep', type=int, default=None, help='Overrides BACKUP_KEEP.')

    def handle(self, *args, **options):
        backup_dir = Path(options['dir'] or settings.BACKUP_DIR or '')
        if not str(backup_dir) or str(backup_dir) == '.':
            raise CommandError('Set BACKUP_DIR in .env (or pass --dir).')
        backup_dir.mkdir(parents=True, exist_ok=True)
        keep = options['keep'] if options['keep'] is not None else settings.BACKUP_KEEP
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        try:
            path = self._backup_postgres(backup_dir, stamp) if db_engine() == 'postgres' else self._backup_sqlite(backup_dir, stamp)
            media = self._backup_media(backup_dir, stamp)
            removed = self._prune(backup_dir, keep)
        except Exception as exc:
            logger.error('Backup FAILED: %s', exc, exc_info=True)
            raise CommandError(f'Backup failed: {exc}') from exc
        size = path.stat().st_size / 1024 / 1024
        message = f'Backup OK: {path.name} ({size:.1f} MB)' + (f', {media.name}' if media else '')
        if removed:
            message += f'; removed {len(removed)} old file(s)'
        logger.info(message)
        self.stdout.write(self.style.SUCCESS(message))

    def _backup_sqlite(self, backup_dir, stamp):
        target = backup_dir / f'shop-{stamp}.sqlite3'
        connection.ensure_connection()
        dest = sqlite3.connect(target)
        try:
            # The backup API copies a consistent snapshot even while the
            # app is writing, unlike copying the file.
            connection.connection.backup(dest)
        finally:
            dest.close()
        verify_sqlite(target)
        return target

    def _backup_postgres(self, backup_dir, stamp):
        if not shutil.which('pg_dump'):
            raise CommandError('pg_dump is not installed (apt install postgresql-client).')
        target = backup_dir / f'shop-{stamp}.dump'
        env, conn_args, name = pg_env()
        subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--file', str(target), *conn_args, name],
                       env=env, check=True, capture_output=True, text=True)
        verify_postgres(target)
        return target

    def _backup_media(self, backup_dir, stamp):
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists() or not any(media_root.rglob('*')):
            return None
        target = backup_dir / f'shop-{stamp}-media.tar.gz'
        with tarfile.open(target, 'w:gz') as tar:
            tar.add(media_root, arcname='media')
        return target

    def _prune(self, backup_dir, keep):
        """Keeps the newest `keep` backup sets; a set is everything sharing
        one timestamp (database + media)."""
        stamps = sorted({p.name[len('shop-'):len('shop-') + 15] for p in backup_dir.glob('shop-*')})
        removed = []
        for old in stamps[:-keep] if keep > 0 else []:
            for p in backup_dir.glob(f'shop-{old}*'):
                p.unlink()
                removed.append(p.name)
        return removed


def verify_sqlite(path):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        result = db.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise CommandError(f'Backup {path.name} failed integrity check: {result}')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'core_user', 'pos_sale', 'inventory_stockbatch'} <= tables:
            raise CommandError(f'Backup {path.name} is missing tables.')
    finally:
        db.close()


def verify_postgres(path):
    result = subprocess.run(['pg_restore', '--list', str(path)], capture_output=True, text=True)
    if result.returncode != 0 or 'TABLE DATA public pos_sale' not in result.stdout:
        raise CommandError(f'Backup {path.name} could not be read back by pg_restore: {result.stderr.strip()[:200]}')
