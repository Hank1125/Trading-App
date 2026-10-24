from django.core.management.base import BaseCommand

from clashroyale.ingest import ingest_battles

from ._common import describe, make_client


class Command(BaseCommand):
    help = 'Poll battlelogs for tracked players and insert new battles.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=8, help='concurrent requests (5-10)')

    def handle(self, *args, **options):
        self.stdout.write(describe(ingest_battles(make_client(), workers=options['workers'])))
