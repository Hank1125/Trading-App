from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone

from .metrics import FORMULA_VERSION
from .models import Battle, CardMetricSnapshot, IngestionRun, Source

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
