import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.db import connection
from django.test import TestCase, override_settings

from clashroyale.models import Card, CardMetricSnapshot
from markets import lmsr, providers, scheduler, services
from markets.models import Account, Market

UTC = timezone.utc
SCOPE = {'namespace': 'replay:test', 'pages': ['P']}
FEEDS = [{'game': 'siege', 'stat_kind': 'operator_ban_rate', 'scope': SCOPE, 'top': 2, 'windows': ['hourly']}]


def t(day, hour, minute=0, second=0):
    return datetime(2026, 5, day, hour, minute, second, tzinfo=UTC)


class SiegeTables:
    """Minimal copies of the two Siege backend tables the provider reads (owned by Alembic in prod)."""

    @staticmethod
    def create():
        with connection.cursor() as cur:
            cur.execute('CREATE TABLE siege_match (id serial PRIMARY KEY, namespace text, page text)')
            cur.execute(
                'CREATE TABLE siege_map_observation (id serial PRIMARY KEY, match_id int, "order" int, '
                'observed_at timestamptz, status text, content jsonb)'
            )

    @staticmethod
    def add_map(at, bans1, bans2, map_name='Bank', namespace='replay:test', page='P'):
        content = {'map': map_name, 't1_bans': bans1, 't2_bans': bans2, 'status': 'finished'}
        with connection.cursor() as cur:
            cur.execute('INSERT INTO siege_match (namespace, page) VALUES (%s, %s) RETURNING id', [namespace, page])
            match_id = cur.fetchone()[0]
            cur.execute(
                'INSERT INTO siege_map_observation (match_id, "order", observed_at, status, content) '
                "VALUES (%s, 1, %s, 'finished', %s)",
                [match_id, at, json.dumps(content)],
            )


class WindowTests(TestCase):
    def test_window_starts(self):
        at = datetime(2026, 11, 12, 15, 42, 9, tzinfo=UTC)  # a Thursday
        self.assertEqual(scheduler.window_start('hourly', at), datetime(2026, 11, 12, 15, tzinfo=UTC))
        self.assertEqual(scheduler.window_start('daily', at), datetime(2026, 11, 12, tzinfo=UTC))
        self.assertEqual(scheduler.window_start('weekly', at), datetime(2026, 11, 9, tzinfo=UTC))  # Monday


class SiegeProviderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        SiegeTables.create()

    def test_value_only_counts_maps_observed_by_then(self):
        SiegeTables.add_map(t(10, 14, 30), ['Mira', 'Kaid'], ['Mira'])
        SiegeTables.add_map(t(10, 15, 30), ['Ash'], ['Kaid'])
        SiegeTables.add_map(t(10, 15, 0), ['Mira'], [], namespace='live')  # other namespace: ignored
        early = providers.value_at('siege', 'operator_ban_rate', 'Mira', SCOPE, t(10, 15))
        late = providers.value_at('siege', 'operator_ban_rate', 'Mira', SCOPE, t(10, 16))
        self.assertEqual((early.numerator, early.denominator), (1, 1))  # banned by both teams: counted once
        self.assertEqual((late.numerator, late.denominator), (1, 2))
        self.assertIsNone(providers.value_at('siege', 'operator_ban_rate', 'Mira', SCOPE, t(10, 14)))
        self.assertEqual(providers.top_subjects('siege', 'operator_ban_rate', SCOPE, t(10, 16), 2), ['Kaid', 'Ash'])


class ClashProviderTests(TestCase):
    def test_card_price_is_latest_snapshot_by_then(self):
        card = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14)
        for hour, price in ((14, '20.7619'), (15, '21.5000')):
            CardMetricSnapshot.objects.create(
                card=card, source='live', formula_version='cr-price-v1', window_start=t(3, hour),
                window_end=t(10, hour), total_appearances=1, appearances=1, wins=1, losses=0, draws=0,
                usage_pct=Decimal(1), adj_win_rate=Decimal(50), price=Decimal(price), is_low_sample=True,
            )  # fmt: skip
        v = providers.value_at('clash_royale', 'card_price', 'Hog Rider', {'source': 'live'}, t(10, 14, 30))
        self.assertEqual(v.fraction, Decimal('20.7619'))
        self.assertEqual(providers.top_subjects('clash_royale', 'card_price', {'source': 'live'}, t(10, 16), 5),
                         ['Hog Rider'])  # fmt: skip


@override_settings(MARKET_FEEDS=FEEDS, MARKET_SETTLEMENT_GRACE_SECONDS=60)
class SchedulerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        SiegeTables.create()

    def test_full_window_lifecycle(self):
        SiegeTables.add_map(t(10, 13, 50), ['Mira'], ['Kaid'])  # Mira 1/1 at 14:00
        r1 = scheduler.tick(t(10, 14, 5))
        r2 = scheduler.tick(t(10, 14, 6))  # idempotent: nothing new
        self.assertEqual((r1['created'], r2['created']), (2, 0))
        mira = Market.objects.get(subject='Mira', opens_at=t(10, 14))
        self.assertEqual((mira.start_numerator, mira.start_denominator), (1, 1))
        self.assertEqual((mira.opens_at, mira.closes_at), (t(10, 14), t(10, 15)))

        alice = services.demo_account('alice', t(10, 14))
        services.execute_trade(account_id=alice.pk, market_id=mira.pk, side='down', action='buy', contracts=10,
                               limit_units=10**9, idempotency_key='a', now=t(10, 14, 10))  # fmt: skip
        SiegeTables.add_map(t(10, 14, 40), ['Ash'], ['Kaid'])  # Mira -> 1/2 during the window: DOWN wins
        SiegeTables.add_map(t(10, 15), ['Ash'], [])  # observed exactly at close: counts (value at close is <= T)
        SiegeTables.add_map(t(10, 15, 0, 30), ['Mira'], [])  # 30 s after close: excluded from this window

        scheduler.tick(t(10, 15, 0, 30))  # closed but within grace: not settled
        mira.refresh_from_db()
        self.assertEqual(mira.status, 'closed')
        before = Account.objects.get(pk=alice.pk).balance_units
        scheduler.tick(t(10, 15, 2))
        mira.refresh_from_db()
        self.assertEqual((mira.status, mira.settlement.outcome), ('settled', 'down'))
        self.assertEqual((mira.settlement.end_numerator, mira.settlement.end_denominator), (1, 3))
        self.assertEqual(Account.objects.get(pk=alice.pk).balance_units - before, 10 * lmsr.PAYOUT_UNITS)

    def test_unchanged_window_voids(self):
        SiegeTables.add_map(t(10, 13, 50), ['Mira'], [])
        scheduler.tick(t(10, 14, 1))
        scheduler.tick(t(10, 15, 5))
        m = Market.objects.get(subject='Mira', opens_at=t(10, 14))  # the 15:00 window opened too
        self.assertEqual((m.status, m.settlement.reason), ('void', 'stat unchanged'))

    def test_no_data_means_no_markets(self):
        self.assertEqual(scheduler.tick(t(10, 14, 1))['created'], 0)
