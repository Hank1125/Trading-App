from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from clashroyale.ingest import compute_snapshots
from clashroyale.models import Source

from ._common import describe


class Command(BaseCommand):
    help = 'Write a CardMetricSnapshot for every non-support card (cr-price-v1).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-end',
            help='ISO datetime, UTC if no offset; truncated to the hour. Default: current hour.',
        )
        parser.add_argument('--source', choices=Source.values, default=Source.LIVE)

    def handle(self, *args, **options):
        window_end = None
        if options['window_end']:
            try:
                window_end = datetime.fromisoformat(options['window_end'])
            except ValueError as exc:
                raise CommandError(f'bad --window-end: {exc}') from exc
            if timezone.is_naive(window_end):
                window_end = window_end.replace(tzinfo=dt_timezone.utc)
        self.stdout.write(describe(compute_snapshots(window_end, options['source'])))
