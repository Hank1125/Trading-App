from datetime import timedelta
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .history import price_chart
from .metrics import FORMULA_VERSION
from .models import Battle, Card, CardMetricSnapshot, IngestionRun, Source

STALE_AFTER = timedelta(hours=2)
# Prices are shown to 2 dp, so a smaller move is "flat" rather than a "+0.00" rise.
_SHOWN = Decimal('0.01')


def _windows(source):
    """The two most recent window_ends with snapshots, newest first."""
    return list(
        CardMetricSnapshot.objects.filter(source=source, formula_version=FORMULA_VERSION)
        .order_by('-window_end')
        .values_list('window_end', flat=True)
        .distinct()[:2]
    )


def stale_since(source=Source.LIVE):
    """The latest snapshot's window_end if it is older than STALE_AFTER (None when fresh or empty)."""
    windows = _windows(source)
    if windows and timezone.now() - windows[0] > STALE_AFTER:
        return windows[0]
    return None


def _direction(change):
    if change is None:
        return 'none'
    shown = change.quantize(_SHOWN)
    return 'up' if shown > 0 else 'down' if shown < 0 else 'flat'


def price_summary(source=Source.LIVE):
    """Latest snapshot per card (highest price first) with its change vs the previous hourly snapshot."""
    windows = _windows(source)
    summary = {'source': source, 'formula_version': FORMULA_VERSION, 'rows': []}
    if not windows:
        return summary

    latest = (
        CardMetricSnapshot.objects.filter(
            source=source, formula_version=FORMULA_VERSION, window_end=windows[0],
        )
        .select_related('card')
        .order_by('-price')
    )
    previous = {}
    if len(windows) > 1:
        previous = dict(
            CardMetricSnapshot.objects.filter(
                source=source, formula_version=FORMULA_VERSION, window_end=windows[1],
            ).values_list('card_id', 'price')
        )

    rows = []
    for rank, snap in enumerate(latest, 1):
        prev = previous.get(snap.card_id)
        change = snap.price - prev if prev is not None else None
        rows.append({
            'rank': rank,
            'snap': snap,
            'prev_price': prev,
            'change': change,
            'change_pct': (change / prev * 100) if change is not None and prev else None,
            'direction': _direction(change),
        })

    first = latest[0] if rows else None
    summary.update(
        rows=rows,
        window_start=first.window_start if first else None,
        window_end=windows[0],
        previous_window_end=windows[1] if len(windows) > 1 else None,
        total_appearances=first.total_appearances if first else 0,
        computed_at=first.computed_at if first else None,
        is_stale=timezone.now() - windows[0] > STALE_AFTER,
        gainers=sum(r['direction'] == 'up' for r in rows),
        losers=sum(r['direction'] == 'down' for r in rows),
    )
    return summary


HISTORY_RANGES = {'24h': timedelta(hours=24), '7d': timedelta(days=7), 'all': None}
HISTORY_MAX_POINTS = 24 * 30


def card_history(request, api_id):
    """One card's hourly price over time, with the usage and win-rate behind each point."""
    card = get_object_or_404(Card, api_id=api_id, is_support=False)
    source = request.GET.get('source', Source.LIVE)
    if source not in Source.values:
        source = Source.LIVE
    rng = request.GET.get('range', '7d')
    if rng not in HISTORY_RANGES:
        rng = '7d'

    snaps = CardMetricSnapshot.objects.filter(card=card, source=source, formula_version=FORMULA_VERSION)
    latest = snaps.order_by('-window_end').first()
    context = {'card': card, 'source': source, 'range': rng, 'ranges': list(HISTORY_RANGES),
               'formula_version': FORMULA_VERSION, 'latest': latest}  # fmt: skip
    if latest is None:
        return render(request, 'clashroyale/card_history.html', context)

    in_range = snaps
    if HISTORY_RANGES[rng]:
        in_range = in_range.filter(window_end__gte=latest.window_end - HISTORY_RANGES[rng])
    points = list(in_range.order_by('-window_end')[:HISTORY_MAX_POINTS])[::-1]  # oldest first

    rows = []
    for prev, snap in zip([None, *points], points, strict=False):
        change = snap.price - prev.price if prev is not None else None
        rows.append({'snap': snap, 'change': change, 'direction': _direction(change)})
    rows.reverse()  # newest first for the table

    first = points[0]
    prev_hour = rows[1]['snap'] if len(rows) > 1 else None
    from markets.models import Market  # lazy: markets depends on this app, not the other way round

    context.update(
        rows=rows,
        chart=price_chart([(s.window_end, s.price) for s in points]),
        change_1h=latest.price - prev_hour.price if prev_hour else None,
        change_range=latest.price - first.price if len(points) > 1 else None,
        direction_1h=_direction(latest.price - prev_hour.price) if prev_hour else 'none',
        direction_range=_direction(latest.price - first.price) if len(points) > 1 else 'none',
        high=max(s.price for s in points),
        low=min(s.price for s in points),
        rank=CardMetricSnapshot.objects.filter(
            source=source, formula_version=FORMULA_VERSION, window_end=latest.window_end, price__gt=latest.price
        ).count() + 1,
        ranked=CardMetricSnapshot.objects.filter(
            source=source, formula_version=FORMULA_VERSION, window_end=latest.window_end
        ).count(),
        is_stale=timezone.now() - latest.window_end > STALE_AFTER,
        market_pk=Market.objects.filter(
            game='clash_royale', subject=card.name, window='hourly', status='open'
        ).order_by('-opens_at').values_list('pk', flat=True).first(),
    )
    return render(request, 'clashroyale/card_history.html', context)


def prices(request):
    source = request.GET.get('source', Source.LIVE)
    if source not in Source.values:
        source = Source.LIVE
    context = price_summary(source)
    if context['rows']:
        context.update(
            last_battles=IngestionRun.objects.filter(kind=IngestionRun.Kind.BATTLES, source=source)
            .exclude(finished_at=None)
            .first(),
            newest_battle=Battle.objects.filter(source=source)
            .order_by('-battle_time')
            .values_list('battle_time', flat=True)
            .first(),
        )
    return render(request, 'clashroyale/prices.html', context)
