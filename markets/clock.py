"""Server-side market clocks, shared by the web process and the worker via the database.

Each game has its own clock: live wall-clock UTC by default, or an accelerated replay clock
(`demo_start + real elapsed * speed`) when a ClockState row exists for that game. Always labelled.
"""

from datetime import datetime, timezone

from markets.models import ClockState


def real_now() -> datetime:
    return datetime.now(timezone.utc)


def now(game: str) -> datetime:
    state = ClockState.objects.filter(game=game).first()
    if state is None:
        return real_now()
    return state.demo_start + (real_now() - state.real_start) * float(state.speed)


def mode(game: str) -> dict:
    state = ClockState.objects.filter(game=game).first()
    if state is None:
        return {'mode': 'live', 'label': 'LIVE DATA / DEMO POINTS', 'speed': 1}
    return {
        'mode': 'replay',
        'label': f'REPLAY ({state.label}, {float(state.speed):g}x) / DEMO POINTS',
        'speed': float(state.speed),
    }
