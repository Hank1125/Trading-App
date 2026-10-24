from django.utils.functional import SimpleLazyObject


def account(request):
    """The session's demo account for the shared header, loaded only if a template uses it."""
    from markets.views import _account

    return {'account': SimpleLazyObject(lambda: _account(request))}
