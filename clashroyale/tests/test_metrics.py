from datetime import datetime, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from clashroyale import metrics


class ComputeCardMetricsTests(SimpleTestCase):
    def test_worked_example_from_spec(self):
        m = metrics.compute_card_metrics(10_000, 2_000, 1_040, 960, 0)
        self.assertEqual(m.usage_pct, Decimal('20.0000'))
        self.assertEqual(m.win_rate, Decimal('52.0000'))
        self.assertEqual(m.adj_win_rate, Decimal('51.9048'))
        self.assertEqual(m.price, Decimal('20.7619'))
        self.assertFalse(m.is_low_sample)

    def test_small_sample_shrinks_toward_50(self):
        m = metrics.compute_card_metrics(1_000, 10, 9, 1, 0)
        self.assertEqual(m.win_rate, Decimal('90.0000'))
        self.assertEqual(m.adj_win_rate, Decimal('53.6364'))
        self.assertTrue(m.is_low_sample)

    def test_unused_card(self):
        m = metrics.compute_card_metrics(1_000, 0, 0, 0, 0)
        self.assertEqual(m.usage_pct, Decimal('0.0000'))
        self.assertIsNone(m.win_rate)
        self.assertEqual(m.adj_win_rate, Decimal('50.0000'))
        self.assertEqual(m.price, Decimal('0.0000'))

    def test_draws_excluded_from_win_rate(self):
        m = metrics.compute_card_metrics(100, 10, 3, 3, 4)
        self.assertEqual(m.win_rate, Decimal('50.0000'))
        self.assertEqual(m.draws, 4)

    def test_only_draws_gives_null_win_rate(self):
        m = metrics.compute_card_metrics(100, 2, 0, 0, 2)
        self.assertIsNone(m.win_rate)
        self.assertEqual(m.adj_win_rate, Decimal('50.0000'))

    def test_price_equals_usage_at_50_percent(self):
        m = metrics.compute_card_metrics(1_000, 400, 200, 200, 0)
        self.assertEqual(m.price, m.usage_pct)

    def test_low_sample_threshold(self):
        self.assertTrue(metrics.compute_card_metrics(1_000, 199, 100, 99, 0).is_low_sample)
        self.assertFalse(metrics.compute_card_metrics(1_000, 200, 100, 100, 0).is_low_sample)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            metrics.compute_card_metrics(0, 0, 0, 0, 0)
        with self.assertRaises(ValueError):
            metrics.compute_card_metrics(10, 5, 1, 1, 1)


class TallyTests(SimpleTestCase):
    def test_mirror_match_counts_one_win_one_loss(self):
        total, counts = metrics.tally_decks([({1, 2}, 'W'), ({1, 3}, 'L')])
        self.assertEqual(total, 2)
        self.assertEqual(counts[1], (2, 1, 1, 0))
        self.assertEqual(counts[2], (1, 1, 0, 0))
        self.assertEqual(counts[3], (1, 0, 1, 0))

    def test_draws_counted_separately(self):
        _, counts = metrics.tally_decks([({1}, 'D'), ({1}, 'D')])
        self.assertEqual(counts[1], (2, 0, 0, 2))


class HelperTests(SimpleTestCase):
    def test_result_for(self):
        self.assertEqual(metrics.result_for(3, 1), 'W')
        self.assertEqual(metrics.result_for(0, 1), 'L')
        self.assertEqual(metrics.result_for(1, 1), 'D')

    def test_hour_floor(self):
        dt = datetime(2026, 10, 24, 14, 37, 12, 5, tzinfo=timezone.utc)
        self.assertEqual(metrics.hour_floor(dt), datetime(2026, 10, 24, 14, tzinfo=timezone.utc))
