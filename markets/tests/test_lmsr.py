import random
from decimal import Decimal

from django.test import SimpleTestCase

from markets import lmsr
from markets.lmsr import LmsrError, MarketState

B = Decimal(100)


def fresh(b=B):
    return MarketState(q_up=0, q_down=0, b=b)


class PriceTests(SimpleTestCase):
    def test_new_market_is_50_50(self):
        s = fresh()
        self.assertEqual(lmsr.price(s, 'up'), Decimal('0.5'))
        self.assertEqual(lmsr.display_price(s, 'up'), 50)
        self.assertEqual(lmsr.display_price(s, 'down'), 50)

    def test_up_and_down_prices_sum_to_one(self):
        s = MarketState(q_up=137, q_down=42, b=B)
        self.assertEqual(lmsr.price(s, 'up') + lmsr.price(s, 'down'), 1)

    def test_buying_up_raises_up_and_lowers_down(self):
        s = lmsr.apply(fresh(), 'up', 50)
        self.assertGreater(lmsr.price(s, 'up'), Decimal('0.5'))
        self.assertLess(lmsr.price(s, 'down'), Decimal('0.5'))

    def test_display_price_is_clamped_to_1_99(self):
        s = MarketState(q_up=5_000, q_down=0, b=B)  # p_up ~ 1 - e^-50
        self.assertEqual(lmsr.display_price(s, 'up'), 99)
        self.assertEqual(lmsr.display_price(s, 'down'), 1)

    def test_larger_b_means_smaller_price_impact(self):
        thin = lmsr.apply(fresh(Decimal(10)), 'up', 10)
        deep = lmsr.apply(fresh(Decimal(1000)), 'up', 10)
        self.assertGreater(lmsr.price(thin, 'up'), lmsr.price(deep, 'up'))


class TradeCostTests(SimpleTestCase):
    def test_worked_example_from_spec(self):
        # 10 UP contracts on a fresh b=100 market: 100 * 100 * ln((e^0.1 + 1) / 2) = 512.49... points
        self.assertEqual(lmsr.buy_cost_units(fresh(), 'up', 10), 51_250)  # rounded up to 512.50

    def test_one_contract_costs_about_the_displayed_price(self):
        self.assertEqual(lmsr.buy_cost_units(fresh(), 'up', 1), 5_013)  # ~50 points

    def test_buy_then_sell_never_profits_the_trader(self):
        rng = random.Random(7)
        for _ in range(200):
            s = MarketState(q_up=rng.randint(0, 2_000), q_down=rng.randint(0, 2_000), b=Decimal(rng.randint(1, 500)))
            side = rng.choice(lmsr.SIDES)
            n = rng.randint(1, 500)
            paid = lmsr.buy_cost_units(s, side, n)
            got = lmsr.sell_proceeds_units(lmsr.apply(s, side, n), side, n)
            self.assertLessEqual(got, paid)

    def test_cost_is_never_more_than_full_payout_or_less_than_zero(self):
        s = MarketState(q_up=0, q_down=3_000, b=B)  # UP is very cheap
        cost = lmsr.buy_cost_units(s, 'up', 1)
        self.assertGreater(cost, 0)
        self.assertLessEqual(cost, lmsr.PAYOUT_UNITS)


class SubsidyBoundTests(SimpleTestCase):
    def test_house_loss_never_exceeds_b_ln2(self):
        rng = random.Random(11)
        bound = lmsr.max_subsidy_units(B)
        self.assertEqual(bound, 693_148)  # 100 * 100 * ln 2 points = 6,931.47..., rounded up
        for _ in range(50):
            s, collected = fresh(), 0
            for _ in range(rng.randint(1, 40)):
                side = rng.choice(lmsr.SIDES)
                if s.q(side) and rng.random() < 0.3:
                    n = rng.randint(1, s.q(side))
                    collected -= lmsr.sell_proceeds_units(s, side, n)
                    s = lmsr.apply(s, side, -n)
                else:
                    n = rng.randint(1, 300)
                    collected += lmsr.buy_cost_units(s, side, n)
                    s = lmsr.apply(s, side, n)
            for winner in lmsr.SIDES:
                house_loss = s.q(winner) * lmsr.PAYOUT_UNITS - collected
                self.assertLessEqual(house_loss, bound)


class ValidationTests(SimpleTestCase):
    def test_rejects_bad_contract_counts(self):
        for bad in (0, -1, lmsr.MAX_CONTRACTS_PER_TRADE + 1, 1.5, True, '3'):
            with self.assertRaises(LmsrError):
                lmsr.buy_cost_units(fresh(), 'up', bad)

    def test_rejects_unknown_side(self):
        with self.assertRaises(LmsrError):
            lmsr.buy_cost_units(fresh(), 'yes', 1)

    def test_cannot_sell_more_than_outstanding(self):
        with self.assertRaises(LmsrError):
            lmsr.sell_proceeds_units(MarketState(q_up=3, q_down=0, b=B), 'up', 4)

    def test_rejects_bad_liquidity_and_state(self):
        for bad_b in (Decimal(0), Decimal(-5), Decimal('1e9'), 100):
            with self.assertRaises(LmsrError):
                MarketState(q_up=0, q_down=0, b=bad_b)
        with self.assertRaises(LmsrError):
            MarketState(q_up=-1, q_down=0, b=B)
