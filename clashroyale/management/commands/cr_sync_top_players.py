from django.core.management.base import BaseCommand

from clashroyale.ingest import sync_top_players

from ._common import describe, make_client


class Command(BaseCommand):
    help = 'Refresh the top-1000 Path of Legends players.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1000)

    def handle(self, *args, **options):
        self.stdout.write(describe(sync_top_players(make_client(), options['limit'])))
