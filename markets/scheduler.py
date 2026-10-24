"""Opens, closes and settles windowed UP/DOWN markets. Run by `manage.py markets_worker` every few seconds.

Feeds (which stats get markets) come from settings.MARKET_FEEDS. Each tick:
1. for each feed x window, if the current window has no market for a top subject, create one with the
   start value frozen at the window start (skipped if the stat has no data yet);
2. close markets whose window ended;
3. settle closed markets past their grace time, using the stat value at the window end.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction

from markets import providers, services
from markets.models import Market

WINDOW_LENGTH = {
    'hourly': timedelta(hours=1),
    'daily': timedelta(days=1),
    'weekly': timedelta(weeks=1),
}

STAT_LABELS = {
    'operator_ban_rate': 'ban rate',
    'map_play_rate': 'play rate',
    'card_price': 'price',
}


def window_start(window: str, at: datetime) -> datetime:
    """Start of the window containing `at`, in UTC: on the hour, at 00:00, or Monday 00:00."""
    start = at.replace(minute=0, second=0, microsecond=0)
    if window in ('daily', 'weekly'):
        start = start.replace(hour=0)
    if window == 'weekly':
        start -= timedelta(days=start.weekday())
    return start


def _title(feed: dict, subject: str, window: str, start: datetime) -> str:
    when = {'hourly': start.strftime('%b %d %H:00 UTC'), 'daily': start.strftime('%b %d'),
            'weekly': 'week of ' + start.strftime('%b %d')}[window]  # fmt: skip
    return f'{subject} {STAT_LABELS[feed["stat_kind"]]} — {window} ({when}): UP or DOWN?'


def open_due_markets(now: datetime) -> int:
    created = 0
    grace = timedelta(seconds=settings.MARKET_SETTLEMENT_GRACE_SECONDS)
    for feed in settings.MARKET_FEEDS:
        for window in feed['windows']:
            start = window_start(window, now)
            subjects = providers.top_subjects(feed['game'], feed['stat_kind'], feed['scope'], start, feed['top'])
            for subject in subjects:
                value = providers.value_at(feed['game'], feed['stat_kind'], subject, feed['scope'], start)
                if value is None or value.denominator <= 0:
                    continue
                try:
                    with transaction.atomic():
                        Market.objects.create(
                            game=feed['game'],
                            stat_kind=feed['stat_kind'],
                            subject=subject,
                            scope=feed['scope'],
                            formula_version=providers.FORMULA_VERSIONS[(feed['game'], feed['stat_kind'])],
                            window=window,
                            opens_at=start,
                            closes_at=start + WINDOW_LENGTH[window],
                            settles_after=start + WINDOW_LENGTH[window] + grace,
                            liquidity_b=Decimal(feed.get('liquidity_b', 100)),
                            start_numerator=value.numerator,
                            start_denominator=value.denominator,
                            title=_title(feed, subject, window, start),
                        )
                    created += 1
                except IntegrityError:
                    pass  # already exists for this window (another tick or worker created it)
    return created


def close_and_settle(now: datetime) -> tuple[int, int]:
    closed = Market.objects.filter(status=Market.Status.OPEN, closes_at__lte=now).update(
        status=Market.Status.CLOSED
    )
    settled = 0
    for m in Market.objects.filter(status=Market.Status.CLOSED, settles_after__lte=now, settlement__isnull=True):
        end = providers.value_at(m.game, m.stat_kind, m.subject, m.scope, m.closes_at)
        evidence = {
            'start': [m.start_numerator, m.start_denominator, m.opens_at.isoformat()],
            'end': [end.numerator, end.denominator, m.closes_at.isoformat()] if end else None,
            'end_evidence': end.evidence if end else None,
            'formula_version': m.formula_version,
        }
        services.settle_market(
            m.pk, end=(end.numerator, end.denominator) if end else None, evidence=evidence, now=now
        )
        settled += 1
    return closed, settled


def tick(now: datetime) -> dict:
    created = open_due_markets(now)
    closed, settled = close_and_settle(now)
    return {'created': created, 'closed': closed, 'settled': settled}
