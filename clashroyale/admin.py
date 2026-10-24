from django.contrib import admin

from .models import (
    Battle,
    BattleDeck,
    BattleDeckCard,
    Card,
    CardMetricSnapshot,
    IngestionRun,
    Player,
)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['name', 'api_id', 'rarity', 'elixir', 'is_support', 'updated_at']
    list_filter = ['rarity', 'is_support']
    search_fields = ['name']


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['tag', 'name', 'last_rank', 'last_seen_in_top', 'last_polled_at']
    search_fields = ['tag', 'name']


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ['kind', 'source', 'status', 'started_at', 'finished_at']
    list_filter = ['kind', 'source', 'status']


class BattleDeckCardInline(admin.TabularInline):
    model = BattleDeckCard
    extra = 0


class BattleDeckInline(admin.TabularInline):
    model = BattleDeck
    extra = 0


@admin.register(Battle)
class BattleAdmin(admin.ModelAdmin):
    list_display = ['battle_time', 'type', 'game_mode', 'source']
    list_filter = ['source', 'type']
    inlines = [BattleDeckInline]


@admin.register(BattleDeck)
class BattleDeckAdmin(admin.ModelAdmin):
    list_display = ['battle', 'side', 'player_tag', 'crowns', 'result']
    inlines = [BattleDeckCardInline]


@admin.register(CardMetricSnapshot)
class CardMetricSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'card', 'window_end', 'formula_version', 'source',
        'usage_pct', 'win_rate', 'adj_win_rate', 'price', 'appearances', 'is_low_sample',
    ]
    list_filter = ['formula_version', 'source', 'is_low_sample']
