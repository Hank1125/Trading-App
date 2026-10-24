from django.core.management.base import BaseCommand

from clashroyale.ingest import sync_cards

from ._common import describe, make_client


class Command(BaseCommand):
    help = 'Upsert the card catalog from /cards.'

    def handle(self, *args, **options):
        self.stdout.write(describe(sync_cards(make_client())))
