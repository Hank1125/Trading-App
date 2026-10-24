"""One server-side clock for markets, shared by the web process and the worker via the database.

Live: wall-clock UTC. Replay demo: `demo_start + (real elapsed) * speed`, so a replayed event plays
out faster than real time (e.g. speed 60 = one demo hour per real minute). Always labelled.
"""

from datetime import datetime, timezone

from markets.models import ClockState


def real_now() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    state = ClockState.objects.filter(pk=1).first()
    if state is None:
        return real_now()
    return state.demo_start + (real_now() - state.real_start) * float(state.speed)


def mode() -> dict:
    state = ClockState.objects.filter(pk=1).first()
    if state is None:
        return {'mode': 'live', 'label': 'LIVE DATA / DEMO POINTS', 'speed': 1}
    return {
        'mode': 'replay',
        'label': f'REPLAY ({state.label}, {float(state.speed):g}x) / DEMO POINTS',
        'speed': float(state.speed),
    }
