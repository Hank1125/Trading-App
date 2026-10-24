from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from clashroyale import history

T = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)


class PriceChartTests(SimpleTestCase):
    def test_nothing_to_draw(self):
        self.assertIsNone(history.price_chart([]))

    def test_points_are_sorted_and_span_the_plot(self):
        c = history.price_chart([(T + timedelta(hours=2), Decimal('21')), (T, Decimal('20')), (T + timedelta(hours=1), Decimal('22'))])
        xs = [d['x'] for d in c['dots']]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual((xs[0], xs[-1]), (history.PAD_L, history.W - history.PAD_R))
        self.assertEqual(c['last']['price'], Decimal('21'))
        self.assertEqual(c['direction'], 'up')
        self.assertTrue(c['path'].startswith(f'M{xs[0]},'))

    def test_y_axis_fits_the_cards_own_range(self):
        c = history.price_chart([(T, Decimal('33.10')), (T + timedelta(hours=1), Decimal('33.30'))])
        top, bottom = history.PAD_T, history.H - history.PAD_B
        ys = [d['y'] for d in c['dots']]
        self.assertTrue(all(top < y < bottom for y in ys))  # padded inside the plot, not squashed at 0..max
        self.assertGreater(ys[0], ys[1])  # higher price is drawn higher (smaller y)
        labels = [float(g['label']) for g in c['grid']]
        self.assertLess(labels[0], 33.10)
        self.assertGreater(labels[-1], 33.30)
        self.assertGreater(labels[0], 30)

    def test_single_point_and_flat_lines_sit_mid_chart(self):
        one = history.price_chart([(T, Decimal('5'))])
        self.assertEqual(one['dots'][0]['x'], (history.PAD_L + history.W - history.PAD_R) / 2)
        flat = history.price_chart([(T, Decimal('5')), (T + timedelta(hours=1), Decimal('5'))])
        self.assertEqual(flat['direction'], 'flat')
        mid = (history.PAD_T + history.H - history.PAD_B) / 2
        self.assertAlmostEqual(flat['dots'][0]['y'], mid, delta=1)

    def test_never_goes_below_zero(self):
        c = history.price_chart([(T, Decimal('0')), (T + timedelta(hours=1), Decimal('0.4'))])
        self.assertGreaterEqual(float(c['grid'][0]['label']), 0)
