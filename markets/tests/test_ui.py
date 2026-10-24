from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase

from clashroyale.models import Card, CardMetricSnapshot
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

    def test_clash_tiles_show_card_icons_and_siege_tiles_an_initial(self):
        Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14,
                            icon_url='https://api-assets.clashroyale.com/cards/300/hog.png')  # fmt: skip
        now = clock.real_now()
        window = dict(opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(minutes=55),
                      settles_after=now + timedelta(minutes=56))  # fmt: skip
        hog = make_market(game='clash_royale', stat_kind='card_price', subject='Hog Rider', scope={'source': 'live'},
                          formula_version='cr-price-v1', start_numerator=20, start_denominator=1, **window)  # fmt: skip
        make_market(**window)  # Siege: Mira
        for url in ('/markets/?game=clash_royale', f'/markets/{hog.pk}/'):
            self.assertIn('src="https://api-assets.clashroyale.com/cards/300/hog.png"',
                          self.client.get(url).content.decode())  # fmt: skip
        self.assertIn('<span class="initial" aria-hidden="true">M</span>',
                      self.client.get('/markets/?game=siege').content.decode())  # fmt: skip

    def test_times_are_labelled_with_the_display_zone_not_utc(self):
        m = make_market(opens_at=clock.real_now() - timedelta(minutes=5),
                        closes_at=clock.real_now() + timedelta(minutes=55),
                        settles_after=clock.real_now() + timedelta(minutes=56))  # fmt: skip
        for url in ('/markets/?game=siege', f'/markets/{m.pk}/'):
            html = self.client.get(url).content.decode()
            self.assertRegex(html, r'\d\d:\d\d(:\d\d)? E[SD]T')  # America/New_York
            self.assertNotRegex(html, r'\d\d:\d\d(:\d\d)? UTC')


def cr_snap(card, window_end, price):
    return CardMetricSnapshot.objects.create(
        card=card, source='live', formula_version='cr-price-v1', window_start=window_end - timedelta(days=7),
        window_end=window_end, total_appearances=1000, appearances=300, wins=150, losses=150, draws=0,
        usage_pct=Decimal(30), adj_win_rate=Decimal(50), price=Decimal(price), is_low_sample=False,
    )  # fmt: skip


class DashboardTests(TestCase):
    def test_empty_install_renders_every_panel_with_guidance(self):
        html = self.client.get('/').content.decode()
        self.assertIn('No price snapshots yet', html)
        self.assertIn('No open markets', html)
        self.assertIn('Your portfolio', html)
        self.assertIn('10,000.00 pts', html)

    def test_clash_movers_link_to_their_open_hourly_market(self):
        now = clock.real_now()
        t1 = now.replace(minute=0, second=0, microsecond=0)
        hog = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14, icon_url='https://x/hog.png')
        zap = Card.objects.create(api_id=2, name='Zap', rarity='common', max_level=16)
        cr_snap(hog, t1 - timedelta(hours=1), '20'); cr_snap(hog, t1, '22')
        cr_snap(zap, t1 - timedelta(hours=1), '10'); cr_snap(zap, t1, '9')
        m = make_market(game='clash_royale', stat_kind='card_price', subject='Hog Rider', scope={'source': 'live'},
                        formula_version='cr-price-v1', start_numerator=22, start_denominator=1, opens_at=t1,
                        closes_at=t1 + timedelta(hours=1), settles_after=t1 + timedelta(hours=1, minutes=20))  # fmt: skip
        resp = self.client.get('/')
        self.assertEqual([r['snap'].card.name for r in resp.context['cr_risers']], ['Hog Rider'])
        self.assertEqual([r['snap'].card.name for r in resp.context['cr_fallers']], ['Zap'])
        html = resp.content.decode()
        self.assertIn(f'href="/markets/{m.pk}/">Hog Rider</a>', html)
        self.assertIn('src="https://x/hog.png"', html)
        self.assertNotIn('Stale', html)

    def test_stale_clash_prices_are_flagged(self):
        card = Card.objects.create(api_id=1, name='Zap', rarity='common', max_level=16)
        cr_snap(card, clock.real_now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=5), '10')
        self.assertIn('Stale: the latest prices are for', self.client.get('/').content.decode())


class ListPolishTests(TestCase):
    def test_tiles_carry_sort_and_search_data_and_the_toolbar_renders(self):
        now = clock.real_now()
        make_market(opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(minutes=55),
                    settles_after=now + timedelta(minutes=56))  # fmt: skip
        html = self.client.get('/markets/?game=siege').content.decode()
        self.assertIn('id="q"', html)
        self.assertIn('<select id="sort"', html)
        self.assertIn('data-name="mira"', html)
        self.assertRegex(html, r'data-value="72\.0000"')  # start value until a current value exists

    def test_clash_list_explains_when_markets_open_and_flags_stale_prices(self):
        html = self.client.get('/markets/?game=clash_royale').content.decode()
        self.assertIn('Clash markets open a few minutes past each hour', html)
        self.assertNotIn('Stale:', html)
        card = Card.objects.create(api_id=1, name='Zap', rarity='common', max_level=16)
        cr_snap(card, clock.real_now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=5), '10')
        self.assertIn('Stale: the latest Clash prices are for', self.client.get('/markets/?game=clash_royale').content.decode())

    def test_trade_forms_disable_their_buttons_while_submitting(self):
        now = clock.real_now()
        m = make_market(opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(minutes=55),
                        settles_after=now + timedelta(minutes=56))  # fmt: skip
        self.assertIn('hx-disabled-elt="find button"', self.client.get(f'/markets/{m.pk}/').content.decode())
        quote = self.client.post(f'/markets/{m.pk}/quote/', {'side': 'up', 'action': 'buy', 'contracts': '5'})
        self.assertIn('hx-disabled-elt="find button"', quote.content.decode())


class BatchedTilesTests(TestCase):
    def test_batched_tiles_match_per_tile_lookups(self):
        from markets import services, views

        now = clock.real_now()
        t1 = now.replace(minute=0, second=0, microsecond=0)
        window = dict(opens_at=t1, closes_at=t1 + timedelta(hours=1), settles_after=t1 + timedelta(hours=1, minutes=20))
        markets = []
        for i, (name, prices) in enumerate([('Hog Rider', ['20', '22']), ('Zap', ['10.5']), ('Mirror', [])]):
            card = Card.objects.create(api_id=i + 1, name=name, rarity='common', max_level=16)
            for h, p in enumerate(prices):
                cr_snap(card, t1 - timedelta(hours=len(prices) - 1 - h), p)
            markets.append(make_market(game='clash_royale', stat_kind='card_price', subject=name,
                                       scope={'source': 'live'}, formula_version='cr-price-v1',
                                       start_numerator=20, start_denominator=1, **window))  # fmt: skip
        markets.append(make_market(**window))  # Siege: falls back to the per-tile provider lookup
        alice, bob = (services.demo_account(k, now) for k in ('alice', 'bob'))
        for who, side, key in ((alice, 'up', 'a'), (bob, 'down', 'b'), (bob, 'up', 'c')):
            services.execute_trade(account_id=who.pk, market_id=markets[0].pk, side=side, action='buy', contracts=5,
                                   limit_units=10**9, idempotency_key=key, now=now)  # fmt: skip
        for m in markets:
            m.refresh_from_db()

        batched = {c['m'].pk: c for c in views._cards(markets, now)}
        for m in markets:
            single = views._card(m, now)
            with self.subTest(m.subject):
                for k in ('cur_pct', 'cur_sample', 'change_pp', 'sides', 'up_price', 'speed'):
                    self.assertEqual(batched[m.pk][k], single[k], k)
        self.assertEqual(batched[markets[0].pk]['sides']['up_people'], 2)
        self.assertEqual(batched[markets[0].pk]['cur_pct'], 2200.0)
        self.assertIsNone(batched[markets[2].pk]['cur_pct'])  # Mirror: no snapshot

    def test_list_query_count_does_not_grow_per_tile(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        now = clock.real_now()
        t1 = now.replace(minute=0, second=0, microsecond=0)
        window = dict(opens_at=t1, closes_at=t1 + timedelta(hours=1), settles_after=t1 + timedelta(hours=1, minutes=20))

        def queries_with(n):
            for i in range(Market.objects.count(), n):
                card = Card.objects.create(api_id=100 + i, name=f'Card {i}', rarity='common', max_level=16)
                cr_snap(card, t1, '10')
                make_market(game='clash_royale', stat_kind='card_price', subject=card.name, scope={'source': 'live'},
                            formula_version='cr-price-v1', start_numerator=10, start_denominator=1, **window)  # fmt: skip
            self.client.get('/markets/?game=clash_royale')  # warm the session/account
            with CaptureQueriesContext(connection) as ctx:
                self.client.get('/markets/?game=clash_royale', HTTP_HX_REQUEST='true')
            return len(ctx.captured_queries)

        self.assertEqual(queries_with(2), queries_with(12))
