"""Ingestion and snapshot jobs. See specs/clash-royale/01-data-sources.md and 03-database.md."""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone as dj_timezone

from . import metrics
from .api import ApiError, NotFound
from .models import (
    Battle,
    BattleDeck,
    BattleDeckCard,
    Card,
    CardMetricSnapshot,
    IngestionRun,
    Player,
    Source,
)

log = logging.getLogger(__name__)

BATTLE_TYPE = 'pathOfLegend'
DECK_SIZE = 8
MAX_ERROR_LINES = 50
# A battlelog this long may have dropped older battles since the last poll.
FULL_BATTLELOG = 25


class Rejected(Exception):
    """A battlelog entry that does not qualify. `count_key` names the run counter to bump."""

    def __init__(self, count_key, detail=''):
        self.count_key = count_key
        super().__init__(detail or count_key)


@dataclass(frozen=True)
class ParsedSide:
    tag: str
    crowns: int
    cards: tuple  # ((api_id, level, evolution_level), ...)
    result: str


@dataclass(frozen=True)
class ParsedBattle:
    key: str
    battle_time: datetime
    type: str
    game_mode: str
    sides: tuple  # (side 0 = lower tag, side 1 = higher tag)


def battle_key(battle_time_raw, tag_a, tag_b):
    lo, hi = sorted([tag_a, tag_b])
    return hashlib.sha256(f'{battle_time_raw}|{lo}|{hi}'.encode()).hexdigest()


def parse_battle_time(raw):
    return datetime.strptime(raw, '%Y%m%dT%H%M%S.%fZ').replace(tzinfo=timezone.utc)


def parse_battle(raw):
    """Parse one battlelog entry, or raise Rejected."""
    if raw.get('type') != BATTLE_TYPE:
        raise Rejected('skipped_type')
    team, opponent = raw.get('team') or [], raw.get('opponent') or []
    if len(team) != 1 or len(opponent) != 1:
        raise Rejected('skipped_not_1v1')

    a, b = team[0], opponent[0]
    if a['tag'] == b['tag']:
        raise Rejected('rejected_bad_deck', f'same tag on both sides: {a["tag"]}')
    sides = []
    for own, other in ((a, b), (b, a)):
        cards = tuple(
            (c['id'], c.get('level', 0), c.get('evolutionLevel', 0)) for c in own.get('cards', [])
        )
        if len(cards) != DECK_SIZE:
            raise Rejected('rejected_bad_deck', f'{own["tag"]} has {len(cards)} cards')
        if len({c[0] for c in cards}) != DECK_SIZE:
            raise Rejected('rejected_bad_deck', f'{own["tag"]} has a duplicate card')
        crowns = own.get('crowns', 0)
        sides.append(ParsedSide(
            tag=own['tag'],
            crowns=crowns,
            cards=cards,
            result=metrics.result_for(crowns, other.get('crowns', 0)),
        ))
    sides.sort(key=lambda s: s.tag)

    return ParsedBattle(
        key=battle_key(raw['battleTime'], a['tag'], b['tag']),
        battle_time=parse_battle_time(raw['battleTime']),
        type=raw['type'],
        game_mode=(raw.get('gameMode') or {}).get('name', ''),
        sides=tuple(sides),
    )


class RunRecorder:
    """Accumulates counts and errors for one IngestionRun."""

    def __init__(self, kind, source):
        self.run = IngestionRun.objects.create(kind=kind, source=source)
        self.counts = {}
        self.errors = []

    def bump(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def error(self, msg):
        log.warning(msg)
        self.bump('errors')
        if len(self.errors) < MAX_ERROR_LINES:
            self.errors.append(msg)

    def finish(self, status=None):
        if status is None:
            status = IngestionRun.Status.PARTIAL if self.errors else IngestionRun.Status.OK
        self.run.status = status
        self.run.counts = self.counts
        self.run.error = '\n'.join(self.errors)
        self.run.finished_at = dj_timezone.now()
        self.run.save()
        return self.run


def sync_cards(client):
    rec = RunRecorder(IngestionRun.Kind.CARDS, Source.LIVE)
    try:
        data = client.cards()
    except ApiError as exc:
        rec.error(str(exc))
        return rec.finish(IngestionRun.Status.FAILED)

    rows = []
    for is_support, items in ((False, data.get('items', [])), (True, data.get('supportItems', []))):
        for c in items:
            rows.append(Card(
                api_id=c['id'],
                name=c['name'],
                rarity=c.get('rarity', ''),
                elixir=c.get('elixirCost'),
                max_level=c.get('maxLevel', 0),
                max_evolution_level=c.get('maxEvolutionLevel', 0),
                icon_url=(c.get('iconUrls') or {}).get('medium', ''),
                is_support=is_support,
            ))
    Card.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=['api_id'],
        update_fields=[
            'name', 'rarity', 'elixir', 'max_level', 'max_evolution_level',
            'icon_url', 'is_support', 'updated_at',
        ],
    )
    rec.bump('cards', sum(not r.is_support for r in rows))
    rec.bump('support_items', sum(r.is_support for r in rows))
    return rec.finish()


def sync_top_players(client, limit=1000):
    rec = RunRecorder(IngestionRun.Kind.LEADERBOARD, Source.LIVE)
    try:
        items = client.top_players(limit)
    except ApiError as exc:
        rec.error(str(exc))
        return rec.finish(IngestionRun.Status.FAILED)
    if not items:
        rec.error('leaderboard returned no players')
        return rec.finish(IngestionRun.Status.FAILED)

    now = dj_timezone.now()
    with transaction.atomic():
        Player.objects.bulk_create(
            [Player(tag=p['tag'], name=p.get('name', ''), last_rank=p.get('rank'), last_seen_in_top=now)
             for p in items],
            update_conflicts=True,
            unique_fields=['tag'],
            update_fields=['name', 'last_rank', 'last_seen_in_top'],
        )
        # Players who dropped out stop being polled; their stored battles stay.
        dropped = (
            Player.objects.exclude(tag__in=[p['tag'] for p in items])
            .filter(last_rank__isnull=False)
            .update(last_rank=None)
        )
    rec.bump('players', len(items))
    rec.bump('dropped', dropped)
    return rec.finish()


def tracked_players():
    return Player.objects.filter(last_rank__isnull=False)


def _store_battle(parsed, run, tracked_tags, card_pks):
    with transaction.atomic():
        battle = Battle.objects.create(
            battle_key=parsed.key,
            battle_time=parsed.battle_time,
            type=parsed.type,
            game_mode=parsed.game_mode,
            source=Source.LIVE,
            ingestion_run=run,
        )
        deck_cards = []
        for side_no, side in enumerate(parsed.sides):
            deck = BattleDeck.objects.create(
                battle=battle,
                side=side_no,
                player_tag=side.tag,
                is_tracked_top1000=side.tag in tracked_tags,
                crowns=side.crowns,
                result=side.result,
            )
            deck_cards += [
                BattleDeckCard(deck=deck, card_id=card_pks[api_id], level=level, evolution_level=evo)
                for api_id, level, evo in side.cards
            ]
        BattleDeckCard.objects.bulk_create(deck_cards)


def ingest_battles(client, workers=8):
    rec = RunRecorder(IngestionRun.Kind.BATTLES, Source.LIVE)
    players = {p.tag: p for p in tracked_players()}
    if not players:
        rec.error('no tracked players; run cr_sync_top_players first')
        return rec.finish(IngestionRun.Status.FAILED)

    card_pks = dict(Card.objects.values_list('api_id', 'id'))
    resynced = False
    tracked_tags = set(players)
    fetched_ok = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.battlelog, tag): tag for tag in players}
        for future in as_completed(futures):
            tag = futures[future]
            player = players[tag]
            try:
                entries = future.result()
            except NotFound:
                rec.bump('player_not_found')
                log.info('player %s not found; skipping', tag)
                continue
            except ApiError as exc:
                rec.error(f'{tag}: {exc}')
                if exc.status == 403:
                    # Wrong IP or bad key: every other request will fail too.
                    for f in futures:
                        f.cancel()
                    rec.bump('players_polled', fetched_ok)
                    return rec.finish(IngestionRun.Status.FAILED)
                continue
            fetched_ok += 1
            rec.bump('fetched_entries', len(entries))

            parsed = []
            for raw in entries:
                try:
                    parsed.append(parse_battle(raw))
                except Rejected as r:
                    rec.bump(r.count_key)
                    if r.count_key.startswith('rejected'):
                        rec.error(f'{tag} {raw.get("battleTime")}: {r}')
                except (KeyError, TypeError, ValueError) as exc:
                    rec.bump('rejected_malformed')
                    rec.error(f'{tag} {raw.get("battleTime")}: malformed entry ({exc!r})')

            if (
                player.last_polled_at
                and len(entries) >= FULL_BATTLELOG
                and parsed
                and min(p.battle_time for p in parsed) > player.last_polled_at
            ):
                rec.bump('possible_gaps')

            existing = set(
                Battle.objects.filter(battle_key__in=[p.key for p in parsed])
                .values_list('battle_key', flat=True)
            )
            for p in parsed:
                if p.key in existing:
                    rec.bump('duplicates')
                    continue
                needed = {c[0] for s in p.sides for c in s.cards}
                if not needed <= card_pks.keys() and not resynced:
                    resynced = True
                    sync_cards(client)
                    card_pks = dict(Card.objects.values_list('api_id', 'id'))
                missing = needed - card_pks.keys()
                if missing:
                    rec.bump('rejected_unknown_card')
                    rec.error(f'{tag} {p.battle_time:%Y-%m-%dT%H:%M:%SZ}: unknown card ids {sorted(missing)}')
                    continue
                try:
                    _store_battle(p, rec.run, tracked_tags, card_pks)
                except IntegrityError:
                    rec.bump('duplicates')
                    continue
                existing.add(p.key)
                rec.bump('new_battles')

            player.last_polled_at = dj_timezone.now()
            player.save(update_fields=['last_polled_at'])

    rec.bump('players_polled', fetched_ok)
    if fetched_ok == 0:
        return rec.finish(IngestionRun.Status.FAILED)
    return rec.finish()


def compute_snapshots(window_end=None, source=Source.LIVE):
    """Write one CardMetricSnapshot per non-support card for the window ending at window_end."""
    window_end = metrics.hour_floor(window_end or dj_timezone.now())
    window_start = window_end - metrics.WINDOW
    rec = RunRecorder(IngestionRun.Kind.METRICS, source)
    rec.counts.update(window_end=window_end.isoformat(), formula_version=metrics.FORMULA_VERSION)

    existing = CardMetricSnapshot.objects.filter(
        window_end=window_end, formula_version=metrics.FORMULA_VERSION, source=source,
    )
    if existing.exists():
        rec.bump('already_computed', existing.count())
        return rec.finish()

    in_window = Q(
        battle__source=source,
        battle__battle_time__gte=window_start,
        battle__battle_time__lt=window_end,
    )
    total = BattleDeck.objects.filter(in_window).count()
    if total == 0:
        rec.error('no data in window')
        return rec.finish(IngestionRun.Status.FAILED)

    per_card = {
        row['card_id']: row
        for row in BattleDeckCard.objects.filter(
            deck__battle__source=source,
            deck__battle__battle_time__gte=window_start,
            deck__battle__battle_time__lt=window_end,
        )
        .values('card_id')
        .annotate(
            n=Count('id'),
            w=Count('id', filter=Q(deck__result='W')),
            l=Count('id', filter=Q(deck__result='L')),
            d=Count('id', filter=Q(deck__result='D')),
        )
    }

    snapshots = []
    for card in Card.objects.filter(is_support=False):
        row = per_card.get(card.id, {'n': 0, 'w': 0, 'l': 0, 'd': 0})
        m = metrics.compute_card_metrics(total, row['n'], row['w'], row['l'], row['d'])
        snapshots.append(CardMetricSnapshot(
            card=card,
            source=source,
            formula_version=metrics.FORMULA_VERSION,
            window_start=window_start,
            window_end=window_end,
            total_appearances=m.total_appearances,
            appearances=m.appearances,
            wins=m.wins,
            losses=m.losses,
            draws=m.draws,
            usage_pct=m.usage_pct,
            win_rate=m.win_rate,
            adj_win_rate=m.adj_win_rate,
            price=m.price,
            is_low_sample=m.is_low_sample,
        ))
    try:
        with transaction.atomic():
            CardMetricSnapshot.objects.bulk_create(snapshots)
    except IntegrityError:
        # Another run wrote this window between our check and insert.
        rec.bump('already_computed', len(snapshots))
        return rec.finish()

    rec.bump('total_appearances', total)
    rec.bump('snapshots', len(snapshots))
    return rec.finish()
