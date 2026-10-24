from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase

from clashroyale.models import Card, CardMetricSnapshot, Source


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
        resp = self.client.get('/')
        self.assertContains(resp, 'No live snapshots yet')

    def test_change_vs_previous_snapshot(self):
        snap(self.up, self.t0, '10'); snap(self.up, self.t1, '12')
        snap(self.down, self.t0, '20'); snap(self.down, self.t1, '15')
        resp = self.client.get('/')
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
        resp = self.client.get('/')
        self.assertEqual(resp.context['rows'][0]['direction'], 'none')

    def test_mock_and_live_not_mixed(self):
        snap(self.up, self.t1, '10', Source.MOCK)
        self.assertContains(self.client.get('/'), 'No live snapshots yet')
        resp = self.client.get('/?source=mock')
        self.assertEqual(len(resp.context['rows']), 1)
        self.assertContains(resp, 'MOCK data')

    def test_stale_warning(self):
        snap(self.up, self.t1 - timedelta(hours=5), '10')
        self.assertContains(self.client.get('/'), 'Stale data')
