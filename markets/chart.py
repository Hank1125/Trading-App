"""Kalshi-style price line for one market: UP price (chance %) over its window, as SVG geometry.

Pure (no ORM): takes (time, price) points, returns path data the template draws. The price is a
step line: it holds until the next trade moves it, like an order-book "last price" chart.
"""

from datetime import datetime

W, H = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 36, 12, 12, 26


def _x(t: datetime, start: datetime, end: datetime) -> float:
    span = (end - start).total_seconds() or 1
    frac = min(max((t - start).total_seconds() / span, 0), 1)
    return round(PAD_L + frac * (W - PAD_L - PAD_R), 1)


def _y(price: float) -> float:
    return round(PAD_T + (1 - price / 100) * (H - PAD_T - PAD_B), 1)


def price_chart(
    opens_at: datetime, closes_at: datetime, now: datetime, points: list[tuple[datetime, int]], current: int
) -> dict:
    """points: (trade time, UP price after trade), any order. Starts at 50 when the market opens."""
    upto = min(max(now, opens_at), closes_at)
    series = [(opens_at, 50), *sorted(p for p in points if opens_at <= p[0] <= upto), (upto, current)]
    d = f'M{_x(series[0][0], opens_at, closes_at)},{_y(series[0][1])}'
    for (_, prev_price), (t, price) in zip(series, series[1:], strict=False):
        x = _x(t, opens_at, closes_at)
        d += f' H{x} V{_y(price)}' if price != prev_price else f' H{x}'
    last_x, last_y = _x(upto, opens_at, closes_at), _y(current)
    area = f'{d} V{_y(0)} H{_x(opens_at, opens_at, closes_at)} Z'
    return {
        'w': W,
        'h': H,
        'path': d,
        'area': area,
        'last_x': last_x,
        'last_y': last_y,
        'current': current,
        'grid': [{'y': _y(p), 'label': f'{p}%'} for p in (0, 25, 50, 75, 100)],
        'x_left': PAD_L,
        'x_right': W - PAD_R,
        'label_y': H - 8,
        'trades': len(points),
    }
