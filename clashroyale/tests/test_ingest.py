from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from clashroyale import metrics
from clashroyale.api import ApiError, NotFound
from clashroyale.ingest import (
    Rejected,
    battle_key,
    compute_snapshots,
    ingest_battles,
    parse_battle,
    sync_cards,
    sync_top_players,
)
from clashroyale.models import (
    Battle,
    BattleDeck,
    BattleDeckCard,
    Card,
    CardMetricSnapshot,
    IngestionRun,
    Player,
    Source,
)

DECK_A = list(range(26000000, 26000008))
DECK_B = list(range(26000004, 26000012))  # shares 4 cards with DECK_A
ALL_IDS = sorted(set(DECK_A + DECK_B))


def side(tag, crowns, ids):
    return {'tag': tag, 'crowns': crowns, 'cards': [{'id': i, 'level': 14} for i in ids]}


def raw_battle(time, a, b, a_crowns=1, b_crowns=0, a_ids=DECK_A, b_ids=DECK_B, type='pathOfLegend'):
    return {
        'type': type,
        'battleTime': time,
        'gameMode': {'name': 'Ranked1v1_NewArena'},
        'team': [side(a, a_crowns, a_ids)],
        'opponent': [side(b, b_crowns, b_ids)],
    }


def cards_payload(ids=ALL_IDS):
    return {
        'items': [{'id': i, 'name': f'Card {i}', 'rarity': 'common', 'maxLevel': 16, 'elixirCost': 3,
                   'iconUrls': {'medium': 'https://example.com/c.png'}} for i in ids],
        'supportItems': [{'id': 159000000, 'name': 'Tower Princess', 'rarity': 'common', 'maxLevel': 16}],
    }


class FakeClient:
    def __init__(self, logs, cards=None, players=None):
        self.logs = logs
        self._cards = cards or cards_payload()
        self._players = players or []
        self.card_calls = 0

    def cards(self):
        self.card_calls += 1
        return self._cards

    def top_players(self, limit=1000):
        return self._players[:limit]

    def battlelog(self, tag):
        result = self.logs[tag]
        if isinstance(result, Exception):
            raise result
        return result


class ParseTests(SimpleTestCase):
    def test_battle_key_independent_of_perspective(self):
        self.assertEqual(battle_key('T', '#A', '#B'), battle_key('T', '#B', '#A'))
        self.assertNotEqual(battle_key('T', '#A', '#B'), battle_key('U', '#A', '#B'))

    def test_parse_orders_sides_by_tag(self):
        p = parse_battle(raw_battle('20261023T224119.000Z', '#Z', '#A', a_crowns=3, b_crowns=1))
        self.assertEqual([s.tag for s in p.sides], ['#A', '#Z'])
        self.assertEqual([s.result for s in p.sides], ['L', 'W'])
        self.assertEqual(p.battle_time, datetime(2026, 10, 23, 22, 41, 19, tzinfo=timezone.utc))

    def test_same_battle_from_either_log_parses_identically(self):
        t = '20261023T224119.000Z'
        mine = parse_battle(raw_battle(t, '#A', '#B', 2, 1, DECK_A, DECK_B))
        theirs = parse_battle(raw_battle(t, '#B', '#A', 1, 2, DECK_B, DECK_A))
        self.assertEqual(mine, theirs)

    def test_rejections(self):
        cases = {
            'skipped_type': raw_battle('T', '#A', '#B', type='clanMate'),
            'rejected_bad_deck': raw_battle('T', '#A', '#B', a_ids=DECK_A[:7]),
        }
        dup = raw_battle('T', '#A', '#B', a_ids=DECK_A[:7] + DECK_A[:1])
        two_v_two = raw_battle('T', '#A', '#B')
        two_v_two['team'].append(side('#C', 1, DECK_A))
        for key, raw in [*cases.items(), ('rejected_bad_deck', dup), ('skipped_not_1v1', two_v_two)]:
            with self.subTest(key), self.assertRaises(Rejected) as ctx:
                parse_battle(raw)
            self.assertEqual(ctx.exception.count_key, key)


class IngestTests(TestCase):
    def setUp(self):
        Player.objects.create(tag='#A', last_rank=1)
        Player.objects.create(tag='#B', last_rank=2)
        t1, t2 = '20261023T100000.000Z', '20261023T110000.000Z'
        shared = raw_battle(t1, '#A', '#B', 3, 0)
        self.logs = {
            '#A': [shared, raw_battle(t2, '#A', '#X', 0, 1), raw_battle(t2, '#A', '#Y', type='clanMate')],
            # The same A-vs-B battle seen from B's side.
            '#B': [raw_battle(t1, '#B', '#A', 0, 3, DECK_B, DECK_A)],
        }
        self.client = FakeClient(self.logs)
        sync_cards(self.client)

    def test_shared_battle_stored_once_and_rerun_is_noop(self):
        run = ingest_battles(self.client, workers=2)
        self.assertEqual(run.status, IngestionRun.Status.OK)
        self.assertEqual(run.counts['new_battles'], 2)
        self.assertEqual(run.counts['duplicates'], 1)
        self.assertEqual(run.counts['skipped_type'], 1)
        self.assertEqual(Battle.objects.count(), 2)
        self.assertEqual(BattleDeck.objects.count(), 4)
        self.assertEqual(BattleDeckCard.objects.count(), 32)

        again = ingest_battles(self.client, workers=2)
        self.assertNotIn('new_battles', again.counts)
        self.assertEqual(again.counts['duplicates'], 3)
        self.assertEqual(Battle.objects.count(), 2)
        self.assertEqual(BattleDeckCard.objects.count(), 32)

    def test_tracked_flag_and_results(self):
        ingest_battles(self.client, workers=1)
        x_deck = BattleDeck.objects.get(player_tag='#X')
        self.assertFalse(x_deck.is_tracked_top1000)
        self.assertEqual(x_deck.result, 'W')
        self.assertTrue(BattleDeck.objects.get(player_tag='#B').is_tracked_top1000)

    def test_unknown_card_resyncs_once_then_skips(self):
        self.logs['#A'].append(raw_battle('20261023T120000.000Z', '#A', '#Z', b_ids=DECK_B[:7] + [99]))
        run = ingest_battles(self.client, workers=1)
        self.assertEqual(self.client.card_calls, 2)  # setUp sync + one resync
        self.assertEqual(run.counts['rejected_unknown_card'], 1)
        self.assertEqual(run.status, IngestionRun.Status.PARTIAL)
        self.assertEqual(Battle.objects.count(), 2)

    def test_player_404_skipped(self):
        self.logs['#B'] = NotFound(404, 'notFound', '/p')
        run = ingest_battles(self.client, workers=1)
        self.assertEqual(run.status, IngestionRun.Status.OK)
        self.assertEqual(run.counts['player_not_found'], 1)

    def test_403_fails_run(self):
        self.logs['#A'] = self.logs['#B'] = ApiError(403, 'accessDenied.invalidIp', '/p')
        run = ingest_battles(self.client, workers=1)
        self.assertEqual(run.status, IngestionRun.Status.FAILED)
        self.assertIn('invalidIp', run.error)

    def test_updates_last_polled_at(self):
        ingest_battles(self.client, workers=1)
        self.assertIsNotNone(Player.objects.get(tag='#A').last_polled_at)


class SyncTests(TestCase):
    def test_sync_cards_upserts_and_flags_support(self):
        client = FakeClient({})
        sync_cards(client)
        sync_cards(client)
        self.assertEqual(Card.objects.filter(is_support=False).count(), len(ALL_IDS))
        self.assertTrue(Card.objects.get(api_id=159000000).is_support)

    def test_sync_top_players_drops_old(self):
        Player.objects.create(tag='#OLD', last_rank=5)
        run = sync_top_players(FakeClient({}, players=[{'tag': '#A', 'name': 'a', 'rank': 1}]))
        self.assertEqual(run.counts, {'players': 1, 'dropped': 1})
        self.assertIsNone(Player.objects.get(tag='#OLD').last_rank)
        self.assertEqual(Player.objects.get(tag='#A').last_rank, 1)


class SnapshotTests(TestCase):
    def setUp(self):
        Player.objects.create(tag='#A', last_rank=1)
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=2)).strftime('%Y%m%dT%H%M%S.000Z')
        older = (now - timedelta(hours=3)).strftime('%Y%m%dT%H%M%S.000Z')
        stale = (now - timedelta(days=8)).strftime('%Y%m%dT%H%M%S.000Z')
        self.raws = [
            raw_battle(recent, '#A', '#B', 3, 0, DECK_A, DECK_B),
            raw_battle(older, '#A', '#C', 1, 1, DECK_A, DECK_A),  # mirror draw
            raw_battle(stale, '#A', '#D', 0, 1),  # outside the 7-day window
        ]
        client = FakeClient({'#A': self.raws})
        sync_cards(client)
        ingest_battles(client, workers=1)

    def test_snapshots_match_pure_tally(self):
        run = compute_snapshots()
        self.assertEqual(run.status, IngestionRun.Status.OK)
        decks = []
        for raw in self.raws[:2]:
            p = parse_battle(raw)
            decks += [([c[0] for c in s.cards], s.result) for s in p.sides]
        total, counts = metrics.tally_decks(decks)
        self.assertEqual(total, 4)

        snaps = {s.card.api_id: s for s in CardMetricSnapshot.objects.select_related('card')}
        self.assertEqual(len(snaps), len(ALL_IDS))  # support item excluded
        for api_id, snap in snaps.items():
            n, w, l, d = counts.get(api_id, (0, 0, 0, 0))
            expected = metrics.compute_card_metrics(total, n, w, l, d)
            self.assertEqual((snap.appearances, snap.wins, snap.losses, snap.draws), (n, w, l, d))
            self.assertEqual(snap.price, expected.price)
            self.assertEqual(snap.source, Source.LIVE)
            self.assertEqual(snap.formula_version, 'cr-price-v1')
            self.assertEqual(snap.window_end.minute, 0)

        # DECK_A only card: 3 appearances (W, D, D).
        self.assertEqual(snaps[DECK_A[0]].appearances, 3)
        self.assertEqual(snaps[DECK_A[0]].usage_pct, Decimal('75.0000'))

    def test_rerun_same_hour_is_noop(self):
        compute_snapshots()
        n = CardMetricSnapshot.objects.count()
        run = compute_snapshots()
        self.assertEqual(run.counts['already_computed'], n)
        self.assertEqual(CardMetricSnapshot.objects.count(), n)

    def test_mock_source_never_mixes_with_live(self):
        run = compute_snapshots(source=Source.MOCK)
        self.assertEqual(run.status, IngestionRun.Status.FAILED)
        self.assertIn('no data', run.error)
        self.assertFalse(CardMetricSnapshot.objects.exists())
