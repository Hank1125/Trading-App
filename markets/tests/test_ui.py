from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as dj_timezone

from clashroyale.models import Card, CardMetricSnapshot
from markets import chart, clock, lmsr, services, views
from markets.models import ClockState, Market, Trade
from markets.tests.test_trading import make_market

UTC = timezone.utc
T0 = datetime(2026, 11, 6, 14, tzinfo=UTC)


def cr_snap(card, window_end, price):
    return CardMetricSnapshot.objects.create(
        card=card, source='live', formula_version='cr-price-v1', window_start=window_end - timedelta(days=7),
        window_end=window_end, total_appearances=1000, appearances=300, wins=150, losses=150, draws=0,
        usage_pct=Decimal(30), adj_win_rate=Decimal(50), price=Decimal(price), is_low_sample=False,
    )  # fmt: skip


def this_hour():
    return clock.real_now().replace(minute=0, second=0, microsecond=0)


def hourly(start):
    return dict(opens_at=start, closes_at=start + timedelta(hours=1), settles_after=start + timedelta(hours=1, minutes=20))


def clash_market(subject='Hog Rider', start_price=20, **over):
    fields = dict(game='clash_royale', stat_kind='card_price', subject=subject, scope={'source': 'live'},
                  formula_version='cr-price-v1', start_numerator=start_price, start_denominator=1,
                  title=f'{subject} price: UP or DOWN?', **hourly(this_hour()))  # fmt: skip
    fields.update(over)
    return make_market(**fields)


def buy(market, session='alice', side='up', n=10, key='k', at=None):
    account = services.demo_account(session, at or clock.real_now())
    services.execute_trade(account_id=account.pk, market_id=market.pk, side=side, action='buy', contracts=n,
                           limit_units=10**9, idempotency_key=key, now=at or clock.real_now())  # fmt: skip
    return account


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


class MarketPageTests(TestCase):
    def setUp(self):
        self.hog = Card.objects.create(api_id=26000021, name='Hog Rider', rarity='rare', max_level=14, elixir=4,
                                       icon_url='https://x/hog.png')  # fmt: skip

    def test_demo_clock_countdown_is_in_real_seconds(self):
        ClockState.objects.create(game='clash_royale', demo_start=T0, real_start=clock.real_now(),
                                  speed=Decimal(60), label='replay')  # fmt: skip
        cr_snap(self.hog, this_hour(), '20')
        clash_market(**hourly(T0))
        html = self.client.get('/markets/').content.decode()
        self.assertIn('data-deadline', html)
        self.assertRegex(html, r'>(0:59|1:00)<')  # 60 demo minutes at 60x = about 1 real minute, not "60:00"

    def test_markets_tab_is_a_table_with_one_row_per_card(self):
        t1 = this_hour()
        zap = Card.objects.create(api_id=2, name='Zap', rarity='common', max_level=16, elixir=2)
        cr_snap(self.hog, t1 - timedelta(hours=1), '20'); cr_snap(self.hog, t1, '22')
        cr_snap(zap, t1, '9')
        m = clash_market('Hog Rider', 22)
        buy(m, session='bob', n=10, key='b')
        resp = self.client.get('/markets/')
        self.assertEqual([r['snap'].card.name for r in resp.context['rows']], ['Hog Rider', 'Zap'])
        mk = resp.context['rows'][0]['market']
        html = resp.content.decode()
        self.assertIn('<table class="cards">', html)
        self.assertIn('data-name="hog rider"', html)
        self.assertIn('src="https://x/hog.png"', html)
        self.assertIn('<strong>22.00</strong>', html)
        self.assertIn('▲ +2.00', html)
        self.assertIn(f'<a class="btn-trade" href="/markets/{m.pk}/">Trade</a>', html)
        self.assertIn(f'<span class="u">UP {mk["up_price"]}</span>', html)
        self.assertIn(f'<span class="d">{mk["down_price"]} DOWN</span>', html)
        self.assertIn(f'style="width:{mk["up_price"]}%"', html)
        self.assertIn('<span class="ok">▲ 1</span> · <span class="err">▼ 0</span>', html)
        self.assertIn('No market yet', html)  # Zap
        self.assertNotIn('2200', html)

    def test_gap_between_hours_shows_the_closed_market_and_when_the_next_opens(self):
        t1 = this_hour()
        cr_snap(self.hog, t1 - timedelta(hours=1), '20')  # this hour's snapshot isn't written yet (:00-:05)
        last = clash_market('Hog Rider', 20, **hourly(t1 - timedelta(hours=1)))
        buy(last, n=5, key='g', at=t1 - timedelta(minutes=30))
        services.close_market(last.pk, t1)
        closed_at = dj_timezone.localtime(t1).strftime('%H:%M')
        opens = dj_timezone.localtime(t1 + timedelta(minutes=5)).strftime('%H:%M')

        resp = self.client.get('/markets/')
        [row] = resp.context['rows']
        self.assertFalse(row['is_open'])
        self.assertEqual(row['market']['m'].pk, last.pk)
        html = resp.content.decode()
        self.assertIn(f'Closed {closed_at} · settling', html)
        self.assertIn(f'Opens ~{opens}', html)
        self.assertIn('class="split closed"', html)
        self.assertNotIn('>Trade</a>', html)

        html = self.client.get('/').content.decode()
        self.assertIn(f'Last market (closed {closed_at})', html)
        self.assertIn(f'Opens ~{opens}', html)
        self.assertIn(f'<span class="u">UP {row["market"]["up_price"]}</span>', html)

    def test_detail_page_renders_chart_icon_and_history_link(self):
        m = clash_market()
        html = self.client.get(f'/markets/{m.pk}/').content.decode()
        self.assertIn('<svg', html)
        self.assertIn('UP chance', html)
        self.assertIn('src="https://x/hog.png"', html)
        self.assertIn(f'href="/clash/cards/{self.hog.api_id}/"', html)
        self.assertNotIn('maps so far', html)

    def test_detail_page_shows_the_start_price_not_times_100(self):
        m = clash_market(start_price=1749, start_denominator=100)  # 17.49
        html = self.client.get(f'/markets/{m.pk}/').content.decode()
        self.assertIn('= 17.4900', html)
        self.assertNotIn('1749.0', html)

    def test_times_are_labelled_with_the_display_zone_not_utc(self):
        m = clash_market()
        for url in ('/markets/', f'/markets/{m.pk}/'):
            html = self.client.get(url).content.decode()
            self.assertRegex(html, r'\d\d:\d\d(:\d\d)? E[SD]T')  # America/New_York
            self.assertNotRegex(html, r'\d\d:\d\d(:\d\d)? UTC')

    def test_empty_list_explains_when_markets_open_and_flags_stale_prices(self):
        html = self.client.get('/markets/').content.decode()
        self.assertIn('No card prices yet', html)
        self.assertIn('Markets open a few minutes past each hour', html)
        self.assertNotIn('Stale:', html)
        cr_snap(Card.objects.create(api_id=1, name='Zap', rarity='common', max_level=16), this_hour() - timedelta(hours=5), '10')
        self.assertIn('Stale: the latest Clash prices are for', self.client.get('/markets/').content.decode())

    def test_trade_forms_disable_their_buttons_while_submitting(self):
        m = clash_market()
        self.assertIn('hx-disabled-elt="find button"', self.client.get(f'/markets/{m.pk}/').content.decode())
        quote = self.client.post(f'/markets/{m.pk}/quote/', {'side': 'up', 'action': 'buy', 'contracts': '5'})
        self.assertIn('hx-disabled-elt="find button"', quote.content.decode())

    def test_recently_settled_shows_prices_not_times_100(self):
        start = this_hour() - timedelta(hours=2)
        m = clash_market(start_price=20, **hourly(start))
        services.close_market(m.pk, start + timedelta(hours=1))
        services.settle_market(m.pk, end=(43, 2), evidence={}, now=start + timedelta(hours=1, minutes=21))
        html = self.client.get('/markets/').content.decode()
        self.assertIn('<td>20.00</td>', html)
        self.assertIn('<td>21.50</td>', html)


class SiegeRemovedTests(TestCase):
    def test_leftover_siege_rows_are_hidden_and_not_tradable(self):
        # The 0004 migration keeps Siege markets someone traded (so no balance changes); they must stay invisible.
        siege = make_market(game='siege', stat_kind='operator_ban_rate', subject='Mira', scope={'namespace': 'x'},
                            formula_version='pro-ban-rate-v1', **hourly(this_hour()))  # fmt: skip
        clash_market()
        html = self.client.get('/markets/').content.decode()
        self.assertNotIn('Mira', html)
        self.assertEqual(self.client.get(f'/markets/{siege.pk}/').status_code, 404)
        args = {'side': 'up', 'action': 'buy', 'contracts': '5'}
        self.assertEqual(self.client.post(f'/markets/{siege.pk}/quote/', args).status_code, 404)
        self.assertEqual(self.client.post(f'/markets/{siege.pk}/trade/', {**args, 'limit': '99999', 'key': 'k'}).status_code, 404)
        self.assertFalse(Trade.objects.exists())

    def test_no_page_mentions_siege_and_the_nav_has_four_tabs(self):
        for url in ('/', '/markets/', '/markets/portfolio/', '/markets/account/', '/clash/prices/'):
            html = self.client.get(url).content.decode()
            with self.subTest(url):
                self.assertNotRegex(html, r'(?i)siege|liquipedia|ubisoft')
                nav = html[html.index('<nav class="nav">'):html.index('</nav>')]
                self.assertEqual([t for t in ('Dashboard', 'Markets', 'Portfolio', 'Account') if t in nav],
                                 ['Dashboard', 'Markets', 'Portfolio', 'Account'])  # fmt: skip
                self.assertNotIn('Clash prices', nav)


class DashboardTests(TestCase):
    def test_empty_install_explains_what_to_do(self):
        html = self.client.get('/').content.decode()
        self.assertIn('No card prices yet', html)
        self.assertIn('none yet; trade a card to light it up', html)

    def test_every_card_is_a_tile_linking_to_its_market_or_history(self):
        t1 = this_hour()
        hog = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14, icon_url='https://x/hog.png')
        zap = Card.objects.create(api_id=2, name='Zap', rarity='common', max_level=16, elixir=2)
        cr_snap(hog, t1 - timedelta(hours=1), '20'); cr_snap(hog, t1, '22')
        cr_snap(zap, t1 - timedelta(hours=1), '10'); cr_snap(zap, t1, '9')
        m = clash_market('Hog Rider', 22)
        resp = self.client.get('/')
        self.assertEqual([t['snap'].card.name for t in resp.context['tiles']], ['Hog Rider', 'Zap'])
        html = resp.content.decode()
        self.assertIn('<a class="main" href="/clash/cards/1/"', html)  # the card itself opens its price history
        self.assertIn(f'<a class="btn-trade" href="/markets/{m.pk}/">Trade</a>', html)
        self.assertIn('No market for this card yet', html)  # Zap
        self.assertIn('class="btn-trade off"', html)
        self.assertIn('src="https://x/hog.png"', html)
        self.assertIn('▲ +2.00', html)
        self.assertIn('▼ -1.00', html)
        self.assertIn('2 elixir', html)
        self.assertNotIn('Stale', html)

    def test_most_traded_cards_in_the_last_hour_glow_gold(self):
        t1 = this_hour()
        markets = {}
        for i, name in enumerate(['Hog Rider', 'Zap', 'Knight']):
            cr_snap(Card.objects.create(api_id=i + 1, name=name, rarity='common', max_level=16), t1, '10')
            markets[name] = clash_market(name, 10)
        buy(markets['Hog Rider'], n=30, key='a')
        buy(markets['Zap'], n=5, key='b')
        old = Trade.objects.get(idempotency_key='b')
        Trade.objects.filter(pk=old.pk).update(created_at=clock.real_now() - timedelta(hours=2))  # outside the hour
        resp = self.client.get('/')
        hot = {t['snap'].card.name: t['hot'] for t in resp.context['tiles']}
        self.assertEqual(hot['Hog Rider']['contracts'], 30)
        self.assertIsNone(hot['Zap'])
        self.assertIsNone(hot['Knight'])
        html = resp.content.decode()
        self.assertEqual(html.count('class="tile cardtile hot"'), 1)
        self.assertIn('🔥 30 traded', html)

    def test_only_the_top_five_are_hot(self):
        t1 = this_hour()
        for i in range(7):
            name = f'Card {i}'
            cr_snap(Card.objects.create(api_id=i + 1, name=name, rarity='common', max_level=16), t1, '10')
            buy(clash_market(name, 10), n=i + 1, key=f'k{i}')
        hot = {t['snap'].card.name for t in self.client.get('/').context['tiles'] if t['hot']}
        self.assertEqual(hot, {f'Card {i}' for i in range(2, 7)})

    def test_markets_table_marks_the_same_cards_hot(self):
        m = clash_market()
        buy(m, n=3)
        cr_snap(Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14), this_hour(), '20')
        self.assertRegex(self.client.get('/markets/').content.decode(), r'<tr class="\w+ hot"')

    def test_stale_prices_are_flagged(self):
        cr_snap(Card.objects.create(api_id=1, name='Zap', rarity='common', max_level=16), this_hour() - timedelta(hours=5), '10')
        self.assertIn('Stale: the latest prices are for', self.client.get('/').content.decode())


class PortfolioTests(TestCase):
    def test_empty_portfolio(self):
        html = self.client.get('/markets/portfolio/').content.decode()
        self.assertIn('No open positions', html)
        self.assertIn('Starting balance', html)  # the 10,000-point grant in the activity list
        self.assertIn('TrueMarket wallet integration is coming', html)

    def test_open_position_is_valued_at_what_selling_now_returns(self):
        m = clash_market()
        self.client.get('/markets/portfolio/')
        account = services.demo_account(self.client.session.session_key, clock.real_now())
        services.execute_trade(account_id=account.pk, market_id=m.pk, side='up', action='buy', contracts=10,
                               limit_units=10**9, idempotency_key='p', now=clock.real_now())  # fmt: skip
        buy(m, session='bob', n=20, key='q')  # someone else pushes UP higher: our position gains
        m.refresh_from_db()
        resp = self.client.get('/markets/portfolio/')
        [row] = resp.context['active']
        account.refresh_from_db()
        sell_now = services.quote_units(m, 'up', 'sell', 10)
        self.assertEqual(row['value'], sell_now)
        self.assertEqual(row['pnl'], sell_now - row['p'].net_cost_units)
        self.assertGreater(row['pnl'], 0)
        self.assertEqual(resp.context['equity'], account.balance_units + sell_now)
        self.assertIn('UP × 10', resp.content.decode())

    def test_settled_position_moves_to_results_with_its_payout(self):
        start = this_hour() - timedelta(hours=2)
        m = clash_market(**hourly(start))
        self.client.get('/markets/portfolio/')
        account = services.demo_account(self.client.session.session_key, clock.real_now())
        services.execute_trade(account_id=account.pk, market_id=m.pk, side='up', action='buy', contracts=10,
                               limit_units=10**9, idempotency_key='p', now=start + timedelta(minutes=5))  # fmt: skip
        services.close_market(m.pk, start + timedelta(hours=1))
        services.settle_market(m.pk, end=(25, 1), evidence={}, now=start + timedelta(hours=1, minutes=21))  # UP wins
        resp = self.client.get('/markets/portfolio/')
        self.assertEqual(resp.context['active'], [])
        [row] = resp.context['history']
        self.assertEqual(row['value'], 10 * lmsr.PAYOUT_UNITS)  # 10 winning contracts x 100 pts
        self.assertEqual(resp.context['realized'], row['value'] - row['p'].net_cost_units)
        self.assertIn('<span class="kind payout">payout</span>', resp.content.decode())


class AccountTests(TestCase):
    def test_account_shows_name_balance_and_pending_budget(self):
        html = self.client.get('/markets/account/').content.decode()
        self.assertIn('Trader ', html)
        self.assertIn('10,000.00', html)
        self.assertIn('Set via TrueMarket (coming soon)', html)
        self.assertIn('<dt>Trades placed</dt><dd>0</dd>', html)


class BatchedTilesTests(TestCase):
    def test_batched_tiles_match_per_tile_lookups(self):
        t1 = this_hour()
        markets = []
        for i, (name, prices) in enumerate([('Hog Rider', ['20', '22']), ('Zap', ['10.5']), ('Mirror', [])]):
            card = Card.objects.create(api_id=i + 1, name=name, rarity='common', max_level=16)
            for h, p in enumerate(prices):
                cr_snap(card, t1 - timedelta(hours=len(prices) - 1 - h), p)
            markets.append(clash_market(name, 20))
        for session, side, key in (('alice', 'up', 'a'), ('bob', 'down', 'b'), ('bob', 'up', 'c')):
            buy(markets[0], session=session, side=side, n=5, key=key)
        for m in markets:
            m.refresh_from_db()

        now = clock.real_now()
        batched = {c['m'].pk: c for c in views._cards(markets, now)}
        for m in markets:
            single = views._card(m, now)
            with self.subTest(m.subject):
                for k in ('cur_pct', 'cur_sample', 'change_pp', 'sides', 'up_price', 'speed'):
                    self.assertEqual(batched[m.pk][k], single[k], k)
        self.assertEqual(batched[markets[0].pk]['sides']['up_people'], 2)
        self.assertEqual(batched[markets[0].pk]['cur_pct'], 22.0)  # the price itself, not x100
        self.assertIsNone(batched[markets[2].pk]['cur_pct'])  # Mirror: no snapshot

    def test_closed_markets_are_valued_at_their_close_like_the_provider(self):
        t1 = this_hour()
        card = Card.objects.create(api_id=1, name='Hog Rider', rarity='rare', max_level=14)
        for h, p in ((2, '20'), (1, '21'), (0, '25')):
            cr_snap(card, t1 - timedelta(hours=h), p)
        closed = clash_market('Hog Rider', 20, **hourly(t1 - timedelta(hours=2)))  # closed an hour ago
        services.close_market(closed.pk, t1 - timedelta(hours=1))
        closed.refresh_from_db()
        now = clock.real_now()
        [batched] = views._cards([closed], now)
        self.assertEqual(batched['cur_pct'], views._card(closed, now)['cur_pct'])
        self.assertEqual(batched['cur_pct'], 21.0)  # the price at its close, not today's 25

    def _queries_with(self, n, url):
        for i in range(Card.objects.count(), n):
            card = Card.objects.create(api_id=100 + i, name=f'Card {i}', rarity='common', max_level=16)
            cr_snap(card, this_hour(), '10')
            buy(clash_market(card.name, 10), n=1, key=f'k{i}')  # traded, so the hot lookup has rows too
        self.client.get(url)  # warm the session/account
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url, HTTP_HX_REQUEST='true')
        return len(ctx.captured_queries)

    def test_markets_list_query_count_does_not_grow_per_tile(self):
        self.assertEqual(self._queries_with(2, '/markets/'), self._queries_with(12, '/markets/'))

    def test_dashboard_query_count_does_not_grow_per_tile(self):
        self.assertEqual(self._queries_with(2, '/'), self._queries_with(12, '/'))
