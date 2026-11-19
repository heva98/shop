"""What lets the backend run on several servers: one copy of each
scheduled job at a time, health checks a load balancer can use, request
ids in the logs, and reports read from a replica when there is one."""

import logging
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core import jobs
from core.db_routing import REPLICA, ReplicaRouter, on_replica
from core.models import JobLease
from core.request_id import RequestIdFilter, current


class SingleFlightTests(TestCase):
    def test_a_second_copy_is_refused_while_the_first_runs(self):
        with jobs.single_flight('nightly', minutes=5):
            with self.assertRaises(jobs.JobAlreadyRunning):
                with jobs.single_flight('nightly', minutes=5):
                    self.fail('ran twice at once')

    def test_the_lease_is_free_again_once_the_job_ends(self):
        with jobs.single_flight('nightly', minutes=5):
            pass
        ran = False
        with jobs.single_flight('nightly', minutes=5):
            ran = True
        self.assertTrue(ran)

    def test_the_lease_is_freed_when_the_job_fails(self):
        with self.assertRaises(ValueError):
            with jobs.single_flight('nightly', minutes=5):
                raise ValueError
        self.assertIsNotNone(jobs.acquire('nightly', minutes=5))

    def test_a_crashed_holders_lease_runs_out(self):
        self.assertIsNotNone(jobs.acquire('nightly', minutes=5))  # never released
        self.assertIsNone(jobs.acquire('nightly', minutes=5))
        JobLease.objects.filter(name='nightly').update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNotNone(jobs.acquire('nightly', minutes=5))

    def test_jobs_do_not_block_each_other(self):
        with jobs.single_flight('a', minutes=5), jobs.single_flight('b', minutes=5):
            pass

    def test_a_late_release_does_not_free_someone_elses_lease(self):
        first = jobs.acquire('nightly', minutes=5)
        JobLease.objects.filter(name='nightly').update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNotNone(jobs.acquire('nightly', minutes=5))  # a second server took over
        jobs.release('nightly', first)                              # the first wakes up and lets go
        self.assertIsNone(jobs.acquire('nightly', minutes=5))      # the second still holds it

    def test_the_daily_summaries_skip_while_another_copy_runs(self):
        out = StringIO()
        with jobs.single_flight('send_daily_summaries', minutes=5):
            call_command('send_daily_summaries', stdout=out)
        self.assertIn('already sending', out.getvalue())


class HealthTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_live_and_ready_answer_ok(self):
        for url in ('/api/health/live/', '/api/health/ready/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertEqual(response.json()['status'], 'ok')

    def test_a_stale_backup_fails_the_monitor_but_not_readiness(self):
        with tempfile.TemporaryDirectory() as empty, override_settings(BACKUP_DIR=empty):
            self.assertEqual(self.client.get('/api/health/').status_code, 503)
            self.assertEqual(self.client.get('/api/health/ready/').status_code, 200)

    def test_not_ready_without_a_working_cache(self):
        with mock.patch('core.health.cache.get', return_value=None):
            response = self.client.get('/api/health/ready/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['cache'], 'not storing')


class RequestIdTests(TestCase):
    def test_each_response_gets_an_id(self):
        first = self.client.get('/api/health/live/')['X-Request-ID']
        second = self.client.get('/api/health/live/')['X-Request-ID']
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_the_proxys_id_is_kept(self):
        response = self.client.get('/api/health/live/', HTTP_X_REQUEST_ID='abc-123')
        self.assertEqual(response['X-Request-ID'], 'abc-123')

    def test_an_unsafe_id_is_replaced(self):
        response = self.client.get('/api/health/live/', HTTP_X_REQUEST_ID='bad\nid')
        self.assertNotIn('\n', response['X-Request-ID'])
        self.assertNotEqual(response['X-Request-ID'], 'bad\nid')

    def test_djangos_own_error_line_carries_the_id(self):
        seen = []

        class Capture(logging.Handler):
            def emit(self, record):
                seen.append(record.request_id)

        handler = Capture(level=logging.ERROR)
        handler.addFilter(RequestIdFilter())
        logger = logging.getLogger('django.request')
        logger.addHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as empty, override_settings(BACKUP_DIR=empty):
                self.client.get('/api/health/', HTTP_X_REQUEST_ID='trace-me')  # 503, logged by Django
        finally:
            logger.removeHandler(handler)
        self.assertEqual(seen, ['trace-me'])
        self.assertEqual(current(), '-')  # cleared once the request is over


class ReplicaRouterTests(SimpleTestCase):
    router = ReplicaRouter()

    def read_db(self):
        return self.router.db_for_read(JobLease)

    def test_reads_use_the_primary_outside_marked_views(self):
        with mock.patch.dict(settings.DATABASES, {REPLICA: {}}):
            self.assertIsNone(self.read_db())

    def test_marked_views_read_from_the_replica(self):
        with mock.patch.dict(settings.DATABASES, {REPLICA: {}}):
            self.assertEqual(on_replica(self.read_db)(), REPLICA)
            self.assertIsNone(self.read_db())  # and only while the view runs

    def test_without_a_replica_everything_uses_the_primary(self):
        self.assertNotIn(REPLICA, settings.DATABASES)
        self.assertIsNone(on_replica(self.read_db)())

    def test_writes_and_migrations_always_use_the_primary(self):
        with mock.patch.dict(settings.DATABASES, {REPLICA: {}}):
            self.assertEqual(on_replica(lambda: self.router.db_for_write(JobLease))(), 'default')
        self.assertFalse(self.router.allow_migrate(REPLICA, 'core'))
        self.assertTrue(self.router.allow_migrate('default', 'core'))
