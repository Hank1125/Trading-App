from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from clashroyale.models import Card, CardMetricSnapshot
from markets import clock, lmsr, providers, scheduler, services
from markets.models import Account, ClockState, Market

UTC = timezone.utc


def t(day, hour, minute=0, second=0):
    return datetime(2026, 5, day, hour, minute, second, tzinfo=UTC)


CR_FEEDS = [{'game': 'clash_royale', 'stat_kind': 'card_price', 'scope': {'source': 'live'}, 'top': 2,
             'windows': ['hourly'], 'exact_time': True, 'grace_seconds': 1200}]  # fmt: skip


def cr_snapshot(card, hour, price, day=10):
    return CardMetricSnapshot.objects.create(
        card=card, source='live', formula_version='cr-price-v1', window_start=t(day - 7, hour),
        window_end=t(day, hour), total_appearances=1, appearances=1, wins=1, losses=0, draws=0,
        usage_pct=Decimal(1), adj_win_rate=Decimal(50), price=Decimal(price), is_low_sample=True,
    )  # fmt: skip


class WindowTests(TestCase):
    def test_window_starts(self):
        at = datetime(2026, 11, 12, 15, 42, 9, tzinfo=UTC)  # a Thursday
        self.assertEqual(scheduler.window_start('hourly', at), datetime(2026, 11, 12, 15, tzinfo=UTC))
        self.assertEqual(scheduler.window_start('daily', at), datetime(2026, 11, 12, tzinfo=UTC))
        self.assertEqual(scheduler.window_start('weekly', at), datetime(2026, 11, 9, tzinfo=UTC))  # Monday


class ClashProviderTests(TestCase):
    def test_card_price_is_latest_snapshot_by_then(self):
        card = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14)
        cr_snapshot(card, 14, '20.7619')
        cr_snapshot(card, 15, '21.5000')
        v = providers.value_at('clash_royale', 'card_price', 'Hog Rider', {'source': 'live'}, t(10, 14, 30))
        self.assertEqual(v.fraction, Decimal('20.7619'))
        self.assertIsNone(providers.value_at('clash_royale', 'card_price', 'Hog Rider', {'source': 'live'}, t(10, 13)))
        self.assertEqual(providers.top_subjects('clash_royale', 'card_price', {'source': 'live'}, t(10, 16), 5),
                         ['Hog Rider'])  # fmt: skip

    def test_other_games_are_rejected(self):
        with self.assertRaises(ValueError):
            providers.value_at('siege', 'operator_ban_rate', 'Mira', {}, t(10, 14))
        with self.assertRaises(ValueError):
            providers.top_subjects('siege', 'operator_ban_rate', {}, t(10, 14), 5)


@override_settings(MARKET_FEEDS=CR_FEEDS)
class ClashLifecycleTests(TestCase):
    def setUp(self):
        self.hog = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14)
        self.zap = Card.objects.create(api_id=2, name='Zap', rarity='common', max_level=16)

    def test_full_window_lifecycle(self):
        cr_snapshot(self.hog, 14, '20.0000')
        cr_snapshot(self.zap, 14, '10.0000')
        r1 = scheduler.tick(t(10, 14, 6))
        r2 = scheduler.tick(t(10, 14, 7))  # idempotent: nothing new
        self.assertEqual((r1['created'], r2['created']), (2, 0))
        hog = Market.objects.get(subject='Hog Rider', opens_at=t(10, 14))
        self.assertEqual(hog.start_numerator / hog.start_denominator, 20)
        self.assertEqual((hog.opens_at, hog.closes_at), (t(10, 14), t(10, 15)))

        alice = services.demo_account('alice', t(10, 14))
        services.execute_trade(account_id=alice.pk, market_id=hog.pk, side='down', action='buy', contracts=10,
                               limit_units=10**9, idempotency_key='a', now=t(10, 14, 10))  # fmt: skip
        cr_snapshot(self.hog, 15, '19.5000')  # cr_hourly writes the 15:00 price: it fell, DOWN wins

        scheduler.tick(t(10, 15, 10))  # closed but within the 20-min grace: not settled yet
        hog.refresh_from_db()
        self.assertEqual(hog.status, 'closed')
        before = Account.objects.get(pk=alice.pk).balance_units
        scheduler.tick(t(10, 15, 21))
        hog.refresh_from_db()
        self.assertEqual((hog.status, hog.settlement.outcome), ('settled', 'down'))
        self.assertEqual(hog.settlement.end_numerator / hog.settlement.end_denominator, 19.5)
        self.assertEqual(Account.objects.get(pk=alice.pk).balance_units - before, 10 * lmsr.PAYOUT_UNITS)

    def test_unchanged_window_voids(self):
        cr_snapshot(self.hog, 14, '20.0000')
        scheduler.tick(t(10, 14, 6))
        cr_snapshot(self.hog, 15, '20.0000')
        scheduler.tick(t(10, 15, 21))
        m = Market.objects.get(subject='Hog Rider', opens_at=t(10, 14))
        self.assertEqual((m.status, m.settlement.reason), ('void', 'stat unchanged'))

    def test_no_data_means_no_markets(self):
        self.assertEqual(scheduler.tick(t(10, 14, 6))['created'], 0)


@override_settings(MARKET_FEEDS=CR_FEEDS)
class ClashExactSnapshotTests(TestCase):
    def setUp(self):
        self.hog = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14)

    def test_opens_only_once_the_window_start_snapshot_exists_and_settles_on_the_end_snapshot(self):
        cr_snapshot(self.hog, 13, '20.0000')
        self.assertEqual(scheduler.tick(t(10, 14, 2))['created'], 0)  # 14:00 snapshot not written yet
        cr_snapshot(self.hog, 14, '20.0000')  # cr_hourly writes it at ~14:05
        self.assertEqual(scheduler.tick(t(10, 14, 6))['created'], 1)
        m = Market.objects.get()
        self.assertEqual(m.start_numerator / m.start_denominator, 20)
        scheduler.tick(t(10, 15, 10))  # closed, within the 20-min grace: waits for the 15:00 snapshot
        self.assertFalse(Market.objects.filter(settlement__isnull=False).exists())
        cr_snapshot(self.hog, 15, '21.2500')
        scheduler.tick(t(10, 15, 21))
        m.refresh_from_db()
        self.assertEqual((m.status, m.settlement.outcome), ('settled', 'up'))

    def test_missing_end_snapshot_voids_instead_of_comparing_stale_prices(self):
        cr_snapshot(self.hog, 14, '20.0000')
        scheduler.tick(t(10, 14, 6))
        scheduler.tick(t(10, 15, 21))  # no 15:00 snapshot ever arrived
        m = Market.objects.get(opens_at=t(10, 14))
        self.assertEqual((m.status, m.settlement.reason), ('void', 'no data at window end'))

    def test_top_none_opens_a_market_for_every_card(self):
        names = ['Hog Rider', 'Knight', 'Zap']
        for i, name in enumerate(names):
            card = self.hog if name == 'Hog Rider' else Card.objects.create(
                api_id=10 + i, name=name, rarity='common', max_level=16)  # fmt: skip
            cr_snapshot(card, 14, f'{10 + i}.0000')
        with self.settings(MARKET_FEEDS=[{**CR_FEEDS[0], 'top': None}]):
            self.assertEqual(scheduler.tick(t(10, 14, 6))['created'], 3)
        self.assertEqual(sorted(Market.objects.values_list('subject', flat=True)), names)


class DemoClockTests(TestCase):
    def test_a_demo_clock_runs_its_game_fast_and_is_labelled(self):
        self.assertEqual(clock.mode('clash_royale')['mode'], 'live')
        ClockState.objects.create(game='clash_royale', demo_start=t(10, 15), real_start=clock.real_now(),
                                  speed=Decimal(60), label='demo')  # fmt: skip
        self.assertLess(abs((clock.now('clash_royale') - t(10, 15)).total_seconds()), 120)
        self.assertEqual(clock.mode('clash_royale')['mode'], 'replay')
        self.assertIn('demo, 60x', clock.mode('clash_royale')['label'])

    def test_command_needs_a_start_and_can_stop(self):
        with self.assertRaises(CommandError):
            call_command('markets_demo_clock', stdout=StringIO())
        call_command('markets_demo_clock', start='2026-11-06T14:00:00+00:00', speed='60', stdout=StringIO())
        self.assertEqual(ClockState.objects.get().game, 'clash_royale')
        call_command('markets_demo_clock', stop=True, stdout=StringIO())
        self.assertFalse(ClockState.objects.exists())
