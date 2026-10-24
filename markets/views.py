import uuid

from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from markets import clock, lmsr, providers, services
from markets.models import Account, Market, Position, Trade


def _account(request) -> Account:
    """The demo account tied to this browser's session (server-side identity; never from the request body)."""
    if not request.session.session_key:
        request.session.save()
    return services.demo_account(request.session.session_key, clock.real_now())


def _card(m: Market, now) -> dict:
    """Everything a market tile shows: prices, live stat vs start, countdown, people on each side."""
    state = services.state_of(m)
    start_pct = 100 * m.start_numerator / m.start_denominator
    cur = providers.value_at(m.game, m.stat_kind, m.subject, m.scope, min(now, m.closes_at))
    cur_pct = cur.percent if cur else None
    return {
        'm': m,
        'up_price': lmsr.display_price(state, 'up'),
        'down_price': lmsr.display_price(state, 'down'),
        'start_pct': start_pct,
        'cur_pct': cur_pct,
        'cur_sample': cur.denominator if cur else None,
        'change_pp': None if cur_pct is None else cur_pct - start_pct,
        'seconds_left': max(int((m.closes_at - now).total_seconds()), 0),
        'sides': services.sides_summary(m),
        'unit': '' if m.stat_kind == 'card_price' else '%',
    }


def _header(request, game: str) -> dict:
    account = _account(request)
    return {'account': account, 'clock': clock.mode(game), 'now': clock.now(game), 'game': game}


def market_list(request):
    window = request.GET.get('window', 'hourly')
    game = request.GET.get('game', 'siege')
    if window not in Market.Window.values or game not in Market.Game.values:
        return HttpResponseBadRequest('unknown window or game')
    ctx = _header(request, game)
    now = ctx['now']
    markets = Market.objects.filter(window=window, game=game, opens_at__lte=now, closes_at__gt=now)
    ctx.update(
        window=window,
        game=game,
        cards=[_card(m, now) for m in markets.order_by('stat_kind', 'subject')],
        recent=Market.objects.filter(game=game, window=window, status__in=['settled', 'void'])
        .select_related('settlement')
        .order_by('-closes_at')[:8],
    )
    template = 'markets/_market_grid.html' if request.headers.get('HX-Request') else 'markets/list.html'
    return render(request, template, ctx)


def market_detail(request, pk: int):
    market = get_object_or_404(Market, pk=pk)
    ctx = _header(request, market.game)
    ctx.update(
        card=_card(market, ctx['now']),
        position=Position.objects.filter(account=ctx['account'], market=market).first(),
        trades=Trade.objects.filter(market=market)[:15],
        settlement=getattr(market, 'settlement', None),
    )
    template = 'markets/_detail_live.html' if request.headers.get('HX-Request') else 'markets/detail.html'
    return render(request, template, ctx)


def _trade_args(request):
    try:
        contracts = int(request.POST.get('contracts', ''))
    except ValueError:
        raise Http404 from None
    return request.POST.get('side', ''), request.POST.get('action', ''), contracts


@require_POST
def quote(request, pk: int):
    """Step 1: show the exact cost/proceeds and lock it in as the trade's limit."""
    market = get_object_or_404(Market, pk=pk)
    side, action, contracts = _trade_args(request)
    ctx = {'market': market, 'side': side, 'action': action, 'contracts': contracts}
    try:
        ctx['units'] = services.quote_units(market, side, action, contracts)
        ctx['key'] = uuid.uuid4().hex
    except (services.TradeError, lmsr.LmsrError) as e:
        ctx['error'] = str(e)
    return render(request, 'markets/_quote.html', ctx)


@require_POST
def trade(request, pk: int):
    """Step 2: execute at the quoted limit (rejected with a fresh quote if the price moved)."""
    account = _account(request)
    side, action, contracts = _trade_args(request)
    ctx = {'market_id': pk}
    try:
        result = services.execute_trade(
            account_id=account.pk,
            market_id=pk,
            side=side,
            action=action,
            contracts=contracts,
            limit_units=int(request.POST.get('limit', '-1')),
            idempotency_key=request.POST.get('key', ''),
            now=clock.now(Market.objects.get(pk=pk).game),
        )
        ctx['trade'] = result.trade
    except services.TradeError as e:
        ctx['error'] = str(e)
        ctx['fresh_units'] = e.quote_units
    except Market.DoesNotExist:
        raise Http404 from None
    return render(request, 'markets/_trade_result.html', ctx)


def portfolio(request):
    ctx = _header(request, request.GET.get('game', 'siege') if request.GET.get('game') in Market.Game.values else 'siege')
    account = ctx['account']
    positions = (
        Position.objects.filter(account=account)
        .select_related('market')
        .order_by('-market__closes_at')
    )
    ctx.update(
        positions=positions,
        trades=Trade.objects.filter(account=account).select_related('market')[:30],
        ledger=account.ledger.order_by('-created_at', '-id')[:30],
    )
    return render(request, 'markets/portfolio.html', ctx)
