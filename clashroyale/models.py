"""Clash Royale data models. See specs/clash-royale/03-database.md."""

from django.db import models


class Source(models.TextChoices):
    LIVE = 'live', 'Live'
    MOCK = 'mock', 'Mock'


class Card(models.Model):
    api_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)
    rarity = models.CharField(max_length=20)
    elixir = models.SmallIntegerField(null=True, blank=True)
    max_level = models.SmallIntegerField()
    max_evolution_level = models.SmallIntegerField(default=0)
    icon_url = models.URLField(max_length=500, blank=True)
    # Tower troops (API "supportItems"); excluded from v1 metrics.
    is_support = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Player(models.Model):
    tag = models.CharField(max_length=20, unique=True)  # stored with leading '#'
    name = models.CharField(max_length=100, blank=True)
    last_rank = models.IntegerField(null=True, blank=True)
    last_seen_in_top = models.DateTimeField(null=True, blank=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} ({self.tag})'


class IngestionRun(models.Model):
    class Kind(models.TextChoices):
        CARDS = 'cards', 'Cards'
        LEADERBOARD = 'leaderboard', 'Leaderboard'
        BATTLES = 'battles', 'Battles'
        METRICS = 'metrics', 'Metrics'

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        OK = 'ok', 'OK'
        PARTIAL = 'partial', 'Partial'
        FAILED = 'failed', 'Failed'

    kind = models.CharField(max_length=20, choices=Kind.choices)
    source = models.CharField(max_length=10, choices=Source.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    counts = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.kind} {self.source} {self.started_at:%Y-%m-%d %H:%M} [{self.status}]'


class Battle(models.Model):
    # sha256(battleTime | min(tag) | max(tag)); see specs/clash-royale/02-metrics.md
    battle_key = models.CharField(max_length=64, unique=True)
    battle_time = models.DateTimeField(db_index=True)
    type = models.CharField(max_length=40)
    game_mode = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices)
    ingestion_run = models.ForeignKey(
        IngestionRun, on_delete=models.PROTECT, related_name='battles'
    )

    class Meta:
        indexes = [models.Index(fields=['source', 'battle_time'])]

    def __str__(self):
        return f'{self.type} @ {self.battle_time:%Y-%m-%d %H:%M}'


class BattleDeck(models.Model):
    class Result(models.TextChoices):
        WIN = 'W', 'Win'
        LOSS = 'L', 'Loss'
        DRAW = 'D', 'Draw'

    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name='decks')
    # 0 = lower tag, 1 = higher tag, independent of whose battlelog it came from.
    side = models.SmallIntegerField(choices=[(0, '0'), (1, '1')])
    player_tag = models.CharField(max_length=20, db_index=True)
    is_tracked_top1000 = models.BooleanField(default=False)
    crowns = models.SmallIntegerField()
    result = models.CharField(max_length=1, choices=Result.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['battle', 'side'], name='uniq_battle_side'),
        ]

    def __str__(self):
        return f'{self.player_tag} side {self.side} ({self.result})'


class BattleDeckCard(models.Model):
    deck = models.ForeignKey(BattleDeck, on_delete=models.CASCADE, related_name='cards')
    card = models.ForeignKey(Card, on_delete=models.PROTECT, related_name='deck_uses')
    level = models.SmallIntegerField()
    evolution_level = models.SmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['deck', 'card'], name='uniq_deck_card'),
        ]


class CardMetricSnapshot(models.Model):
    card = models.ForeignKey(Card, on_delete=models.PROTECT, related_name='snapshots')
    source = models.CharField(max_length=10, choices=Source.choices)
    formula_version = models.CharField(max_length=20)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    computed_at = models.DateTimeField(auto_now_add=True)

    total_appearances = models.IntegerField()  # N
    appearances = models.IntegerField()  # n_c
    wins = models.IntegerField()
    losses = models.IntegerField()
    draws = models.IntegerField()

    usage_pct = models.DecimalField(max_digits=7, decimal_places=4)
    win_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    adj_win_rate = models.DecimalField(max_digits=7, decimal_places=4)
    price = models.DecimalField(max_digits=10, decimal_places=4)
    is_low_sample = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['card', 'window_end', 'formula_version', 'source'],
                name='uniq_card_snapshot',
            ),
        ]
        indexes = [
            models.Index(fields=['card', 'formula_version', 'source', 'window_end']),
        ]

    def __str__(self):
        return f'{self.card} {self.formula_version} {self.window_end:%Y-%m-%d} price={self.price}'
