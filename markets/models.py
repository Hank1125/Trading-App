"""Shared virtual-points trading engine: accounts, append-only ledger, Kalshi-style UP/DOWN markets.

See specs/markets/. Money is integer units (1 point = 100 units). Virtual points only.
"""

from django.db import models
from django.db.models import Q


class Account(models.Model):
    class Kind(models.TextChoices):
        USER = 'user'
        HOUSE = 'house'  # the market maker's counterparty account; may go negative (bounded by b*ln2)

    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.USER)
    name = models.CharField(max_length=60)
    session_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    balance_units = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind='house') | Q(balance_units__gte=0), name='user_balance_nonnegative'
            ),
            models.UniqueConstraint(fields=['kind'], condition=Q(kind='house'), name='single_house_account'),
        ]

    def __str__(self):
        return f'{self.name} ({self.balance_units / 100:.2f} pts)'


class Market(models.Model):
    class Game(models.TextChoices):
        SIEGE = 'siege'
        CLASH_ROYALE = 'clash_royale'

    class Window(models.TextChoices):
        HOURLY = 'hourly'
        DAILY = 'daily'
        WEEKLY = 'weekly'

    class Status(models.TextChoices):
        OPEN = 'open'
        CLOSED = 'closed'
        SETTLED = 'settled'
        VOID = 'void'

    # Frozen rules (never edited after creation).
    game = models.CharField(max_length=20, choices=Game.choices)
    stat_kind = models.CharField(max_length=40)  # e.g. operator_ban_rate, map_play_rate, card_price
    subject = models.CharField(max_length=100)  # operator / map / card name
    scope = models.JSONField()  # e.g. {"namespace": ..., "pages": [...]} or {"source": "live"}
    formula_version = models.CharField(max_length=40)
    window = models.CharField(max_length=6, choices=Window.choices)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    settles_after = models.DateTimeField()
    liquidity_b = models.DecimalField(max_digits=10, decimal_places=2)
    start_numerator = models.BigIntegerField()
    start_denominator = models.BigIntegerField()
    title = models.CharField(max_length=200)

    # Mutable trading state.
    q_up = models.BigIntegerField(default=0)
    q_down = models.BigIntegerField(default=0)
    status = models.CharField(max_length=7, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['game', 'stat_kind', 'subject', 'window', 'opens_at'], name='one_market_per_window'
            ),
            models.CheckConstraint(condition=Q(opens_at__lt=models.F('closes_at')), name='opens_before_close'),
            models.CheckConstraint(
                condition=Q(closes_at__lte=models.F('settles_after')), name='settles_after_close'
            ),
            models.CheckConstraint(condition=Q(q_up__gte=0, q_down__gte=0), name='q_nonnegative'),
            models.CheckConstraint(condition=Q(start_denominator__gt=0), name='start_value_defined'),
        ]
        indexes = [models.Index(fields=['status', 'closes_at'])]

    def __str__(self):
        return self.title


class Position(models.Model):
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='positions')
    market = models.ForeignKey(Market, on_delete=models.PROTECT, related_name='positions')
    up_contracts = models.BigIntegerField(default=0)
    down_contracts = models.BigIntegerField(default=0)
    net_cost_units = models.BigIntegerField(default=0)  # total paid for buys minus received from sells

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'market'], name='one_position_per_market'),
            models.CheckConstraint(
                condition=Q(up_contracts__gte=0, down_contracts__gte=0), name='contracts_nonnegative'
            ),
        ]


class Trade(models.Model):
    class Side(models.TextChoices):
        UP = 'up'
        DOWN = 'down'

    class Action(models.TextChoices):
        BUY = 'buy'
        SELL = 'sell'

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='trades')
    market = models.ForeignKey(Market, on_delete=models.PROTECT, related_name='trades')
    side = models.CharField(max_length=4, choices=Side.choices)
    action = models.CharField(max_length=4, choices=Action.choices)
    contracts = models.IntegerField()
    units = models.BigIntegerField()  # paid (buy) or received (sell), always positive
    up_price_after = models.IntegerField()  # displayed UP price (1-99) right after this trade
    idempotency_key = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'idempotency_key'], name='trade_idempotency'),
            models.CheckConstraint(condition=Q(contracts__gt=0, units__gte=0), name='trade_positive'),
        ]
        ordering = ['-created_at', '-id']


class Settlement(models.Model):
    class Outcome(models.TextChoices):
        UP = 'up'
        DOWN = 'down'
        VOID = 'void'

    market = models.OneToOneField(Market, on_delete=models.PROTECT, related_name='settlement')
    outcome = models.CharField(max_length=4, choices=Outcome.choices)
    reason = models.CharField(max_length=200)
    end_numerator = models.BigIntegerField(null=True)
    end_denominator = models.BigIntegerField(null=True)
    evidence = models.JSONField()
    total_paid_units = models.BigIntegerField()
    settled_at = models.DateTimeField()


class LedgerEntry(models.Model):
    """Append-only. Every balance change is one entry; sum of entries == account balance."""

    class Kind(models.TextChoices):
        GRANT = 'grant'
        TRADE = 'trade'
        PAYOUT = 'payout'
        REFUND = 'refund'

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='ledger')
    delta_units = models.BigIntegerField()
    kind = models.CharField(max_length=6, choices=Kind.choices)
    operation_id = models.CharField(max_length=120)
    market = models.ForeignKey(Market, null=True, blank=True, on_delete=models.PROTECT)
    trade = models.ForeignKey(Trade, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'operation_id'], name='ledger_operation_once'),
        ]
