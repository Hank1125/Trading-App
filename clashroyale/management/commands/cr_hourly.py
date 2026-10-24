from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from clashroyale.ingest import compute_snapshots, ingest_battles, sync_cards, sync_top_players
from clashroyale.models import IngestionRun, Source

from ._common import describe, make_client

# Arbitrary constant for pg_try_advisory_lock so two hourly runs never overlap.
LOCK_ID = 7_260_001
LEADERBOARD_MAX_AGE = timedelta(hours=24)


class Command(BaseCommand):
    help = 'Hourly job: sync cards, refresh leaderboard if >24h old, ingest battles, compute metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=8)

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_ID])
            if not cur.fetchone()[0]:
                self.stdout.write('another cr_hourly run is in progress; exiting')
                return
        try:
            self._run(options['workers'])
        finally:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(%s)', [LOCK_ID])

    def _run(self, workers):
        started = timezone.now()
        self.stdout.write(f'cr_hourly started {started:%Y-%m-%d %H:%M:%S}Z')
        client = make_client()

        self.stdout.write(describe(sync_cards(client)))

        recent_leaderboard = IngestionRun.objects.filter(
            kind=IngestionRun.Kind.LEADERBOARD,
            source=Source.LIVE,
            status=IngestionRun.Status.OK,
            started_at__gte=started - LEADERBOARD_MAX_AGE,
        ).exists()
        if not recent_leaderboard:
            self.stdout.write(describe(sync_top_players(client)))

        battles = ingest_battles(client, workers=workers)
        self.stdout.write(describe(battles))

        # Don't stamp a fresh snapshot on stale data when ingestion fully failed.
        if battles.status == IngestionRun.Status.FAILED:
            self.stdout.write('battle ingestion failed; skipping metrics this hour')
            return
        self.stdout.write(describe(compute_snapshots(started, Source.LIVE)))
        self.stdout.write(f'cr_hourly done in {(timezone.now() - started).total_seconds():.0f}s')
