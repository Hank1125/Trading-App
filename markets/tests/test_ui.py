from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase

from markets import chart, clock
from markets.models import ClockState, Market
from markets.tests.test_trading import make_market

UTC = timezone.utc
T0 = datetime(2026, 11, 6, 14, tzinfo=UTC)


class ChartTests(TestCase):
    def test_step_line_starts_at_50_and_ends_at_current_price(self):
        c = chart.price_chart(T0, T0 + timedelta(hours=1), T0 + timedelta(minutes=30),
                              [(T0 + timedelta(minutes=10), 60)], current=60)  # fmt: skip
        self.assertTrue(c['path'].startswith(f'M{chart._x(T0, T0, T0 + timedelta(hours=1))},{chart._y(50)}'))
        self.assertEqual(c['last_y'], chart._y(60))
        self.assertEqual(c['last_x'], chart._x(T0 + timedelta(minutes=30), T0, T0 + timedelta(hours=1)))
        self.assertEqual(c['trades'], 1)

    def test_points_outside_the_window_or_in_the_future_are_ignored(self):
        c = chart.price_chart(T0, T0 + timedelta(hours=1), T0 + timedelta(minutes=5),
                              [(T0 + timedelta(minutes=40), 90)], current=50)  # fmt: skip
        self.assertNotIn(str(chart._y(90)), c['path'])


class CountdownTests(TestCase):
    def test_replay_countdown_is_in_real_seconds(self):
        ClockState.objects.create(game='siege', demo_start=T0, real_start=clock.real_now(),
                                  speed=Decimal(60), label='replay')  # fmt: skip
        make_market(opens_at=T0, closes_at=T0 + timedelta(hours=1), settles_after=T0 + timedelta(hours=1))
        html = self.client.get('/markets/?game=siege').content.decode()
        self.assertIn('data-deadline', html)
        self.assertRegex(html, r'>(0:59|1:00)<')  # 60 demo minutes at 60x = about 1 real minute, not "60:00"

    def test_detail_page_renders_chart(self):
        m = make_market(opens_at=clock.real_now() - timedelta(minutes=5),
                        closes_at=clock.real_now() + timedelta(minutes=55),
                        settles_after=clock.real_now() + timedelta(minutes=56))  # fmt: skip
        html = self.client.get(f'/markets/{m.pk}/').content.decode()
        self.assertIn('<svg', html)
        self.assertIn('UP chance', html)
        self.assertEqual(Market.objects.count(), 1)


class ClashDisplayTests(TestCase):
    def test_card_price_is_shown_in_points_not_scaled_as_a_percent(self):
        now = clock.real_now()
        make_market(game='clash_royale', stat_kind='card_price', subject='Barbarian Barrel',
                    scope={'source': 'live'}, formula_version='cr-price-v1',
                    start_numerator=163413, start_denominator=5000,  # 32.6826
                    opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(minutes=55),
                    settles_after=now + timedelta(minutes=75))  # fmt: skip
        html = self.client.get('/markets/?game=clash_royale').content.decode()
        self.assertIn('start 32.68 pts', html)
        self.assertIn('meta price', html)
        self.assertNotIn('3268', html)
