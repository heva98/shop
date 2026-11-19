"""Scheduled jobs that must run at most once at a time, across every
server: `with single_flight('daily-summaries', minutes=30): ...`.

The lease is a database row, so it works on SQLite and Postgres alike and
needs no Redis. Taking it is one conditional UPDATE ("set me as holder
where the lease has expired"), which the database applies atomically:
of two servers racing, exactly one sees a row change.

`minutes` must comfortably exceed the job's longest run. If the holder
dies, the lease frees itself at expires_at and the next timer tick runs
the job; the jobs are safe to re-run, so that is enough.
"""

import os
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import JobLease

_NEVER = datetime(2000, 1, 1, tzinfo=dt_timezone.utc)


class JobAlreadyRunning(Exception):
    """Another copy of the job holds the lease."""


def _holder():
    return f'{socket.gethostname()[:40]}:{os.getpid()}:{uuid.uuid4().hex[:8]}'


def acquire(name, *, minutes):
    """The holder token if the lease was free (it is now ours), else None."""
    try:
        with transaction.atomic():
            JobLease.objects.get_or_create(name=name, defaults={'expires_at': _NEVER})
    except IntegrityError:  # another server created the row a moment earlier
        pass
    now, holder = timezone.now(), _holder()
    taken = JobLease.objects.filter(name=name, expires_at__lte=now).update(
        holder=holder, acquired_at=now, expires_at=now + timedelta(minutes=minutes))
    return holder if taken else None


def release(name, holder):
    """Frees the lease, if `holder` still has it."""
    JobLease.objects.filter(name=name, holder=holder).update(holder='', expires_at=timezone.now())


@contextmanager
def single_flight(name, *, minutes):
    """Runs the block only if no other copy of job `name` is running;
    raises JobAlreadyRunning otherwise."""
    holder = acquire(name, minutes=minutes)
    if holder is None:
        raise JobAlreadyRunning(name)
    try:
        yield
    finally:
        release(name, holder)
