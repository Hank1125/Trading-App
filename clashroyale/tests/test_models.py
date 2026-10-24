from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from django.test import TestCase

from clashroyale.models import (
    Battle,
    BattleDeck,
    BattleDeckCard,
    Card,
    IngestionRun,
    Source,
)


class ConstraintTests(TestCase):
    """DB-level guarantees that ingestion relies on to avoid double-counting."""

    def setUp(self):
        self.run = IngestionRun.objects.create(kind=IngestionRun.Kind.BATTLES, source=Source.MOCK)
        self.battle = Battle.objects.create(
            battle_key='a' * 64,
            battle_time=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
            type='pathOfLegend',
            source=Source.MOCK,
            ingestion_run=self.run,
        )
        self.card = Card.objects.create(api_id=26000000, name='Knight', rarity='common', max_level=16)

    def test_duplicate_battle_key_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Battle.objects.create(
                battle_key='a' * 64,
                battle_time=self.battle.battle_time,
                type='pathOfLegend',
                source=Source.MOCK,
                ingestion_run=self.run,
            )

    def test_duplicate_side_rejected(self):
        BattleDeck.objects.create(battle=self.battle, side=0, player_tag='#A', crowns=1, result='W')
        with self.assertRaises(IntegrityError), transaction.atomic():
            BattleDeck.objects.create(battle=self.battle, side=0, player_tag='#B', crowns=0, result='L')

    def test_duplicate_card_in_deck_rejected(self):
        deck = BattleDeck.objects.create(battle=self.battle, side=0, player_tag='#A', crowns=1, result='W')
        BattleDeckCard.objects.create(deck=deck, card=self.card, level=14)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BattleDeckCard.objects.create(deck=deck, card=self.card, level=14)
