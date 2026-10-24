from django import template

register = template.Library()


@register.filter
def pts(units):
    """Integer units -> '1,234.56' points."""
    if units is None:
        return '—'
    return f'{units / 100:,.2f}'


@register.filter
def countdown(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


@register.filter
def signed(value, digits=1):
    if value is None:
        return '—'
    return f'{value:+.{int(digits)}f}'
