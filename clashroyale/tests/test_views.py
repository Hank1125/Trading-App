from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from clashroyale.models import Card, CardMetricSnapshot, Source
from clashroyale.views import price_summary


def snap(card, window_end, price, source=Source.LIVE):
    return CardMetricSnapshot.objects.create(
        card=card, source=source, formula_version='cr-price-v1',
        window_start=window_end - timedelta(days=7), window_end=window_end,
        total_appearances=1000, appearances=300, wins=150, losses=150, draws=0,
        usage_pct=Decimal('30'), win_rate=Decimal('50'), adj_win_rate=Decimal('50'),
        price=Decimal(price), is_low_sample=False,
    )


class PricesViewTests(TestCase):
    def setUp(self):
        self.up = Card.objects.create(api_id=1, name='Riser', rarity='common', max_level=16)
        self.down = Card.objects.create(api_id=2, name='Faller', rarity='rare', max_level=16)
        self.t1 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.t0 = self.t1 - timedelta(hours=1)

    def test_empty_state(self):
        resp = self.client.get(reverse('cr_prices'))
        self.assertContains(resp, 'No live snapshots yet')

    def test_change_vs_previous_snapshot(self):
        snap(self.up, self.t0, '10'); snap(self.up, self.t1, '12')
        snap(self.down, self.t0, '20'); snap(self.down, self.t1, '15')
        resp = self.client.get(reverse('cr_prices'))
        rows = {r['snap'].card.name: r for r in resp.context['rows']}
        self.assertEqual(rows['Riser']['direction'], 'up')
        self.assertEqual(rows['Riser']['change'], Decimal('2'))
        self.assertEqual(rows['Riser']['change_pct'], Decimal('20'))
        self.assertEqual(rows['Faller']['direction'], 'down')
        self.assertEqual(rows['Faller']['change_pct'], Decimal('-25'))
        self.assertEqual([r['snap'].card.name for r in resp.context['rows']], ['Faller', 'Riser'])
        self.assertFalse(resp.context['is_stale'])
        self.assertContains(resp, 'LIVE data')

    def test_first_snapshot_has_no_change(self):
        snap(self.up, self.t1, '10')
        resp = self.client.get(reverse('cr_prices'))
        self.assertEqual(resp.context['rows'][0]['direction'], 'none')

    def test_mock_and_live_not_mixed(self):
        snap(self.up, self.t1, '10', Source.MOCK)
        self.assertContains(self.client.get(reverse('cr_prices')), 'No live snapshots yet')
        resp = self.client.get(reverse('cr_prices') + '?source=mock')
        self.assertEqual(len(resp.context['rows']), 1)
        self.assertContains(resp, 'MOCK data')

    def test_stale_warning(self):
        snap(self.up, self.t1 - timedelta(hours=5), '10')
        self.assertContains(self.client.get(reverse('cr_prices')), 'Stale data')

    def test_page_moved_off_the_site_root(self):
        self.assertEqual(reverse('cr_prices'), '/clash/prices/')


class PriceSummaryTests(TestCase):
    def setUp(self):
        self.card = Card.objects.create(api_id=1, name='Zap', rarity='common', max_level=16)
        self.t1 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.t0 = self.t1 - timedelta(hours=1)

    def test_empty(self):
        self.assertEqual(price_summary()['rows'], [])

    def test_sub_cent_move_is_flat_not_a_plus_zero_rise(self):
        # Shown to 2 dp: +0.004 would render as "+0.00", so it counts as unchanged.
        snap(self.card, self.t0, '24.0400'); snap(self.card, self.t1, '24.0440')
        s = price_summary()
        self.assertEqual(s['rows'][0]['direction'], 'flat')
        self.assertEqual((s['gainers'], s['losers']), (0, 0))

    def test_cent_move_counts(self):
        snap(self.card, self.t0, '24.0400'); snap(self.card, self.t1, '24.0500')
        self.assertEqual(price_summary()['rows'][0]['direction'], 'up')


class CardHistoryTests(TestCase):
    def setUp(self):
        self.card = Card.objects.create(api_id=26000021, name='Hog Rider', rarity='rare', max_level=14, elixir=4,
                                        icon_url='https://x/hog.png')  # fmt: skip
        self.t = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def url(self, **q):
        return reverse('cr_card', args=[self.card.api_id]) + (('?' + '&'.join(f'{k}={v}' for k, v in q.items())) if q else '')

    def test_unknown_and_support_cards_are_404(self):
        self.assertEqual(self.client.get(reverse('cr_card', args=[1])).status_code, 404)
        Card.objects.create(api_id=159000000, name='Tower Princess', rarity='common', max_level=16, is_support=True)
        self.assertEqual(self.client.get(reverse('cr_card', args=[159000000])).status_code, 404)

    def test_no_snapshots_yet(self):
        resp = self.client.get(self.url())
        self.assertContains(resp, 'No live price snapshots for this card yet')

    def test_history_rows_newest_first_with_changes_and_a_chart(self):
        for h, price in ((3, '20'), (2, '21.5'), (1, '21.5'), (0, '19')):
            snap(self.card, self.t - timedelta(hours=h), price)
        resp = self.client.get(self.url())
        rows = resp.context['rows']
        self.assertEqual([r['snap'].price for r in rows], [Decimal('19'), Decimal('21.5'), Decimal('21.5'), Decimal('20')])
        self.assertEqual([r['direction'] for r in rows], ['down', 'flat', 'up', 'none'])
        self.assertEqual(resp.context['change_1h'], Decimal('-2.5'))
        self.assertEqual(resp.context['change_range'], Decimal('-1'))
        self.assertEqual((resp.context['high'], resp.context['low']), (Decimal('21.5'), Decimal('19')))
        self.assertEqual(len(resp.context['chart']['dots']), 4)
        self.assertContains(resp, '<svg')
        self.assertContains(resp, '▼ -2.50 this hour')

    def test_range_filter(self):
        for h in (0, 1, 30, 200):
            snap(self.card, self.t - timedelta(hours=h), '10')
        counts = {r: len(self.client.get(self.url(range=r)).context['rows']) for r in ('24h', '7d', 'all')}
        self.assertEqual(counts, {'24h': 2, '7d': 3, 'all': 4})
        self.assertEqual(self.client.get(self.url(range='bogus')).context['range'], '7d')

    def test_rank_among_cards_in_the_latest_window(self):
        other = Card.objects.create(api_id=2, name='Zap', rarity='common', max_level=16)
        snap(self.card, self.t, '10'); snap(other, self.t, '12')
        resp = self.client.get(self.url())
        self.assertEqual((resp.context['rank'], resp.context['ranked']), (2, 2))

    def test_links_to_the_cards_open_hourly_market(self):
        from markets.models import Market

        snap(self.card, self.t, '10')
        m = Market.objects.create(
            game='clash_royale', stat_kind='card_price', subject='Hog Rider', scope={'source': 'live'},
            formula_version='cr-price-v1', window='hourly', opens_at=self.t, closes_at=self.t + timedelta(hours=1),
            settles_after=self.t + timedelta(hours=1, minutes=20), liquidity_b=Decimal(100),
            start_numerator=10, start_denominator=1, title='Hog Rider price: UP or DOWN?',
        )  # fmt: skip
        self.assertContains(self.client.get(self.url()), f'href="/markets/{m.pk}/"')

    def test_price_table_rows_link_to_each_cards_history(self):
        snap(self.card, self.t, '10')
        html = self.client.get(reverse('cr_prices')).content.decode()
        self.assertIn(f'data-href="/clash/cards/{self.card.api_id}/"', html)
        self.assertIn(f'<a href="/clash/cards/{self.card.api_id}/">Hog Rider</a>', html)
