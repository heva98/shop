"""GET /api/health/ — for an uptime monitor (e.g. UptimeRobot) to poll.

200 when the app can reach its database and, if backups are configured
(BACKUP_DIR), the newest backup is less than BACKUP_MAX_AGE_HOURS old;
503 otherwise, so a silently failing nightly backup pages someone just
like a crashed server would. Reveals nothing beyond ok/not-ok and ages.
"""

import time
from pathlib import Path

from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def newest_backup_age_hours():
    backup_dir = getattr(settings, 'BACKUP_DIR', '')
    if not backup_dir:
        return None
    files = [p for p in Path(backup_dir).glob('shop-*') if p.is_file()]
    if not files:
        return float('inf')
    return (time.time() - max(p.stat().st_mtime for p in files)) / 3600


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def health(request):
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception:  # noqa: BLE001 — any failure means "down"
        checks['database'] = 'unreachable'

    age = newest_backup_age_hours()
    if age is not None:
        if age == float('inf'):
            checks['backup'] = 'none found'
        else:
            checks['backup_age_hours'] = round(age, 1)
            checks['backup'] = 'ok' if age <= settings.BACKUP_MAX_AGE_HOURS else 'stale'

    healthy = checks['database'] == 'ok' and checks.get('backup', 'ok') == 'ok'
    return Response({'status': 'ok' if healthy else 'fail', **checks}, status=200 if healthy else 503)
