from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from .metrics import FORMULA_VERSION
from .models import Battle, CardMetricSnapshot, IngestionRun, Source

STALE_AFTER = timedelta(hours=2)


def _windows(source):
    """The two most recent window_ends with snapshots, newest first."""
    return list(
        CardMetricSnapshot.objects.filter(source=source, formula_version=FORMULA_VERSION)
        .order_by('-window_end')
        .values_list('window_end', flat=True)
        .distinct()[:2]
    )


def prices(request):
    source = request.GET.get('source', Source.LIVE)
    if source not in Source.values:
        source = Source.LIVE
    windows = _windows(source)
    context = {'source': source, 'formula_version': FORMULA_VERSION, 'rows': []}
    if not windows:
        return render(request, 'clashroyale/prices.html', context)

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
            'direction': (
                'none' if change is None else 'up' if change > 0 else 'down' if change < 0 else 'flat'
            ),
        })

    first = latest[0] if rows else None
    last_battles = (
        IngestionRun.objects.filter(kind=IngestionRun.Kind.BATTLES, source=source)
        .exclude(finished_at=None)
        .first()
    )
    newest_battle = (
        Battle.objects.filter(source=source).order_by('-battle_time').values_list('battle_time', flat=True).first()
    )
    context.update(
        rows=rows,
        window_start=first.window_start if first else None,
        window_end=windows[0],
        previous_window_end=windows[1] if len(windows) > 1 else None,
        total_appearances=first.total_appearances if first else 0,
        computed_at=first.computed_at if first else None,
        is_stale=timezone.now() - windows[0] > STALE_AFTER,
        last_battles=last_battles,
        newest_battle=newest_battle,
        gainers=sum(r['direction'] == 'up' for r in rows),
        losers=sum(r['direction'] == 'down' for r in rows),
    )
    return render(request, 'clashroyale/prices.html', context)
