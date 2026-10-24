from django.core.management.base import CommandError

from clashroyale.api import ApiError, ClashRoyaleClient


def make_client():
    try:
        return ClashRoyaleClient()
    except ApiError as exc:
        raise CommandError(str(exc)) from exc


def describe(run):
    line = f'{run.kind}: {run.status} {run.counts}'
    if run.error:
        first = run.error.splitlines()[0]
        line += f'\n  first error: {first}'
    return line
