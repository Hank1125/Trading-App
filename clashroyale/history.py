"""Price-history line for one card: its hourly cr-price-v1 snapshots as SVG geometry.

Pure (no ORM): takes (window_end, price) points, returns what the template draws. The y-axis is
fitted to the card's own range (with padding), since prices differ a lot between cards.
"""

from datetime import datetime
from decimal import Decimal

W, H = 720, 260
PAD_L, PAD_R, PAD_T, PAD_B = 48, 16, 16, 28
TICKS = 4


def _nice_range(lo: float, hi: float) -> tuple[float, float]:
    if hi - lo < 0.02:  # flat line: give it some room so it sits mid-chart
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.12
    return max(lo - pad, 0.0), hi + pad


def price_chart(points: list[tuple[datetime, Decimal]]) -> dict | None:
    """points: (window_end, price), any order. None when there is nothing to draw."""
    series = sorted(points)
    if not series:
        return None
    t0, t1 = series[0][0], series[-1][0]
    span = (t1 - t0).total_seconds() or 1
    lo, hi = _nice_range(float(min(p for _, p in series)), float(max(p for _, p in series)))

    def x(t: datetime) -> float:
        frac = (t - t0).total_seconds() / span if len(series) > 1 else 0.5
        return round(PAD_L + frac * (W - PAD_L - PAD_R), 1)

    def y(price: float) -> float:
        return round(PAD_T + (1 - (price - lo) / (hi - lo)) * (H - PAD_T - PAD_B), 1)

    dots = [{'x': x(t), 'y': y(float(p)), 't': t, 'price': p} for t, p in series]
    path = 'M' + ' L'.join(f'{d["x"]},{d["y"]}' for d in dots)
    area = f'{path} L{dots[-1]["x"]},{H - PAD_B} L{dots[0]["x"]},{H - PAD_B} Z'
    grid = []
    for i in range(TICKS + 1):
        value = lo + (hi - lo) * i / TICKS
        grid.append({'y': y(value), 'label': f'{value:.2f}'})
    first, last = series[0][1], series[-1][1]
    return {
        'w': W,
        'h': H,
        'x_left': PAD_L,
        'x_right': W - PAD_R,
        'label_y': H - 8,
        'path': path,
        'area': area,
        'dots': dots,
        'last': dots[-1],
        'grid': grid,
        'start': t0,
        'end': t1,
        'direction': 'up' if last > first else 'down' if last < first else 'flat',
    }
