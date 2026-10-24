import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

from django.db import connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase

from markets import lmsr, services
from markets.models import Account, LedgerEntry, Market, Position, Settlement, Trade
from markets.services import TradeError

T0 = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)
MAX = 10**12  # "any price" limit for buys


def make_market(**over) -> Market:
    fields = dict(
        game='clash_royale',
        stat_kind='card_price',
        subject='Hog Rider',
        scope={'source': 'live'},
        formula_version='cr-price-v1',
        window='hourly',
        opens_at=T0,
        closes_at=T0 + timedelta(hours=1),
        settles_after=T0 + timedelta(hours=1, minutes=10),
        liquidity_b=Decimal(100),
        start_numerator=72,
        start_denominator=100,
        title='Hog Rider price, 2-3 PM: UP or DOWN?',
    )
    fields.update(over)
    return Market.objects.create(**fields)


def trade(account, market, side='up', action='buy', n=10, limit=MAX, key='k1', at=None):
    return services.execute_trade(
        account_id=account.pk, market_id=market.pk, side=side, action=action, contracts=n,
        limit_units=limit, idempotency_key=key, now=at or T0 + timedelta(minutes=5),
    )  # fmt: skip


def assert_ledger_reconciles(tc):
    for acct in Account.objects.all():
        total = LedgerEntry.objects.filter(account=acct).aggregate(s=Sum('delta_units'))['s'] or 0
        tc.assertEqual(total, acct.balance_units, acct.name)
    grants = LedgerEntry.objects.filter(kind='grant').aggregate(s=Sum('delta_units'))['s'] or 0
    tc.assertEqual(Account.objects.aggregate(s=Sum('balance_units'))['s'], grants)  # points are conserved


class AccountTests(TestCase):
    def test_demo_grant_happens_once(self):
        a = services.demo_account('session-abc', T0)
        again = services.demo_account('session-abc', T0)
        self.assertEqual(a.pk, again.pk)
        self.assertEqual(again.balance_units, 1_000_000)
        self.assertEqual(LedgerEntry.objects.filter(kind='grant').count(), 1)


class TradeTests(TestCase):
    def setUp(self):
        self.alice = services.demo_account('alice-session', T0)
        self.market = make_market()

    def test_buy_moves_price_and_updates_everything_together(self):
        r = trade(self.alice, self.market)
        self.market.refresh_from_db()
        self.alice.refresh_from_db()
        pos = Position.objects.get(account=self.alice, market=self.market)
        self.assertEqual(r.trade.units, 51_250)  # LMSR worked example: 10 UP on a fresh b=100 market
        self.assertEqual(self.alice.balance_units, 1_000_000 - 51_250)
        self.assertEqual((self.market.q_up, pos.up_contracts, pos.net_cost_units), (10, 10, 51_250))
        self.assertGreater(r.trade.up_price_after, 50)
        assert_ledger_reconciles(self)

    def test_sell_returns_points_and_reduces_holding(self):
        trade(self.alice, self.market, n=10, key='buy')
        r = trade(self.alice, self.market, action='sell', n=4, limit=0, key='sell')
        pos = Position.objects.get(account=self.alice, market=self.market)
        self.assertEqual(pos.up_contracts, 6)
        self.assertEqual(pos.net_cost_units, 51_250 - r.trade.units)
        assert_ledger_reconciles(self)

    def test_idempotent_retry_returns_the_original_trade(self):
        first = trade(self.alice, self.market, key='same')
        again = trade(self.alice, self.market, key='same')
        self.assertTrue(again.replayed)
        self.assertEqual(again.trade.pk, first.trade.pk)
        self.assertEqual(Trade.objects.count(), 1)

    def test_same_key_with_different_payload_conflicts(self):
        trade(self.alice, self.market, n=10, key='same')
        with self.assertRaises(TradeError) as e:
            trade(self.alice, self.market, n=11, key='same')
        self.assertEqual(e.exception.code, 'idempotency_conflict')

    def test_trading_closes_exactly_at_close_time_even_if_status_is_still_open(self):
        with self.assertRaises(TradeError) as e:
            trade(self.alice, self.market, at=self.market.closes_at)
        self.assertEqual(e.exception.code, 'market_closed')

    def test_price_moved_past_limit_is_rejected_with_fresh_quote(self):
        with self.assertRaises(TradeError) as e:
            trade(self.alice, self.market, limit=51_249)
        self.assertEqual((e.exception.code, e.exception.quote_units), ('price_moved', 51_250))
        self.assertEqual(Trade.objects.count(), 0)

    def test_rejects_overspending_overselling_and_bad_input(self):
        poor = Account.objects.create(name='poor', session_key='poor')
        cases = [
            (dict(account=poor), 'insufficient_funds'),
            (dict(action='sell', limit=0), 'insufficient_contracts'),
            (dict(n=0), 'bad_contracts'),
            (dict(n=10**9), 'bad_contracts'),
            (dict(side='yes'), 'bad_side'),
            (dict(limit=-1), 'bad_limit'),
        ]
        for over, code in cases:
            args = dict(account=self.alice, market=self.market, key=f'k-{code}-{len(over)}')
            args.update(over)
            with self.subTest(code=code), self.assertRaises(TradeError) as e:
                trade(**args)
            self.assertEqual(e.exception.code, code)
        self.assertEqual(Trade.objects.count(), 0)
        assert_ledger_reconciles(self)


class SettlementTests(TestCase):
    def setUp(self):
        self.alice = services.demo_account('alice-session', T0)
        self.bob = services.demo_account('bob-session', T0)
        self.market = make_market()
        trade(self.alice, self.market, side='up', n=10, key='a')
        trade(self.bob, self.market, side='down', n=5, key='b')
        self.after = self.market.settles_after

    def balances(self):
        return {a.name: Account.objects.get(pk=a.pk).balance_units for a in (self.alice, self.bob)}

    def test_decide_rule(self):
        s = Fraction(72, 100)
        self.assertEqual(services.decide(s, Fraction(73, 100))[0], 'up')
        self.assertEqual(services.decide(s, Fraction(71, 100))[0], 'down')
        self.assertEqual(services.decide(s, Fraction(18, 25))[0], 'void')  # 72/100 == 18/25 exactly
        self.assertEqual(services.decide(s, None)[0], 'void')

    def test_up_wins_pays_100_points_per_contract_once(self):
        before = self.balances()
        s = services.settle_market(self.market.pk, end=(74, 100), evidence={'obs': [1]}, now=self.after)
        again = services.settle_market(self.market.pk, end=(10, 100), evidence={}, now=self.after)
        after = self.balances()
        self.assertEqual((s.outcome, again.pk), ('up', s.pk))
        self.assertEqual(after[self.alice.name] - before[self.alice.name], 10 * lmsr.PAYOUT_UNITS)
        self.assertEqual(after[self.bob.name], before[self.bob.name])
        self.assertEqual(Market.objects.get(pk=self.market.pk).status, 'settled')
        assert_ledger_reconciles(self)

    def test_unchanged_stat_voids_and_refunds_net_cost(self):
        start = {a.pk: 1_000_000 for a in (self.alice, self.bob)}
        s = services.settle_market(self.market.pk, end=(18, 25), evidence={}, now=self.after)
        self.assertEqual((s.outcome, s.reason), ('void', 'stat unchanged'))
        for a in (self.alice, self.bob):
            self.assertEqual(Account.objects.get(pk=a.pk).balance_units, start[a.pk])
        assert_ledger_reconciles(self)

    def test_cannot_settle_early(self):
        with self.assertRaises(TradeError):
            services.settle_market(self.market.pk, end=(74, 100), evidence={}, now=self.market.closes_at)
        self.assertFalse(Settlement.objects.exists())

    def test_sides_summary_counts_people_and_contracts(self):
        self.assertEqual(
            services.sides_summary(Market.objects.get(pk=self.market.pk)),
            {'up_people': 1, 'down_people': 1, 'up_contracts': 10, 'down_contracts': 5},
        )


class ConcurrencyTests(TransactionTestCase):
    def test_concurrent_buys_cannot_overspend(self):
        market = make_market()
        acct = Account.objects.create(name='racer', session_key='racer')
        services.house_account()
        LedgerEntry.objects.create(account=acct, delta_units=60_000, kind='grant', operation_id='g', created_at=T0)
        Account.objects.filter(pk=acct.pk).update(balance_units=60_000)  # enough for ONE 10-contract buy
        errors: list[str] = []

        def buy(key):
            try:
                trade(acct, market, n=10, key=key)
            except TradeError as e:
                errors.append(e.code)
            finally:
                connection.close()

        threads = [threading.Thread(target=buy, args=(f'race-{i}',)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(Trade.objects.count(), 1)
        self.assertEqual(errors, ['insufficient_funds'])
        self.assertGreaterEqual(Account.objects.get(pk=acct.pk).balance_units, 0)
