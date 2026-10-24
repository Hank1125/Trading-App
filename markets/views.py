import uuid
from fractions import Fraction

from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from clashroyale.models import Card, CardMetricSnapshot, Source
from clashroyale.views import price_summary, stale_since
from markets import chart, clock, lmsr, providers, services
from markets.models import Account, Market, Position, Trade


def _account(request) -> Account:
    """The demo account tied to this browser's session (server-side identity; never from the request body)."""
    if not request.session.session_key:
        request.session.save()
    return services.demo_account(request.session.session_key, clock.real_now())


_UNSET = object()


def _card(m: Market, now, mode=None, cur=_UNSET, sides=None) -> dict:
    """Everything a market tile shows: prices, live stat vs start, countdown, people on each side.

    mode, cur and sides can be passed in pre-fetched (see _cards); otherwise each is looked up here.
    """
    state = services.state_of(m)
    speed = (mode or clock.mode(m.game))['speed']
    demo_left = max(int((m.closes_at - now).total_seconds()), 0)
    real_left = demo_left / speed
    start_pct = 100 * m.start_numerator / m.start_denominator
    if cur is _UNSET:
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
        'seconds_left': demo_left,
        # Countdown in REAL seconds (replay clocks run faster than real time); the page ticks it every second.
        'real_seconds_left': real_left,
        'deadline_ms': int((clock.real_now().timestamp() + real_left) * 1000),
        'speed': speed,
        'sides': sides if sides is not None else services.sides_summary(m),
        'unit': '' if m.stat_kind == 'card_price' else '%',
    }


def _clash_prices_by(markets: list[Market], now) -> dict:
    """providers.value_at for many open Clash card-price markets in one query per source.

    Same rule as the provider: the card's latest snapshot with window_end <= as_of (here `now`, since every
    market passed is still open). Keyed by (source, card name).
    """
    wanted = [m for m in markets if m.game == 'clash_royale' and m.stat_kind == 'card_price' and m.closes_at > now]
    out = {}
    for source in {m.scope.get('source', 'live') for m in wanted}:
        names = [m.subject for m in wanted if m.scope.get('source', 'live') == source]
        snaps = (
            CardMetricSnapshot.objects.filter(card__name__in=names, source=source, window_end__lte=now)
            .order_by('card__name', '-window_end', '-id')
            .distinct('card__name')
            .select_related('card')
        )
        for snap in snaps:
            f = Fraction(snap.price)
            evidence = {'card_metric_snapshot_id': snap.pk, 'price': str(snap.price), 'as_of': snap.window_end.isoformat()}
            out[(source, snap.card.name)] = providers.StatPoint(f.numerator, f.denominator, evidence)
    return out


def _cards(markets, now) -> list[dict]:
    """_card for a list of markets with the per-tile lookups batched: clock per game, people per side, Clash prices."""
    markets = list(markets)
    if not markets:
        return []
    modes = {game: clock.mode(game) for game in {m.game for m in markets}}
    people = {
        row['market_id']: row
        for row in Position.objects.filter(market__in=markets)
        .values('market_id')
        .annotate(up=Count('id', filter=Q(up_contracts__gt=0)), down=Count('id', filter=Q(down_contracts__gt=0)))
    }
    prices = _clash_prices_by(markets, now)
    cards = []
    for m in markets:
        p = people.get(m.pk, {})
        sides = {'up_people': p.get('up', 0), 'down_people': p.get('down', 0),
                 'up_contracts': int(m.q_up), 'down_contracts': int(m.q_down)}  # fmt: skip
        key = (m.scope.get('source', 'live'), m.subject)
        batched = m.game == 'clash_royale' and m.stat_kind == 'card_price' and m.closes_at > now
        cards.append(_card(m, now, mode=modes[m.game], sides=sides, cur=prices.get(key) if batched else _UNSET))
    return _with_icons(cards)


def _with_icons(cards: list[dict]) -> list[dict]:
    """Attach each Clash card's icon URL (a market's subject is the card name); Siege has no images."""
    names = [c['m'].subject for c in cards if c['m'].game == 'clash_royale']
    icons = dict(Card.objects.filter(name__in=names).values_list('name', 'icon_url')) if names else {}
    for c in cards:
        c['icon'] = icons.get(c['m'].subject, '')
    return cards


def _header(request, game: str) -> dict:
    account = _account(request)
    return {'account': account, 'clock': clock.mode(game), 'now': clock.now(game), 'game': game}


def _open_markets(game: str, now):
    return Market.objects.filter(game=game, opens_at__lte=now, closes_at__gt=now)


def dashboard(request):
    """Both games at a glance: data mode and freshness, open markets, biggest movers, and the portfolio."""
    account = _account(request)

    cr_now = clock.now('clash_royale')
    cr_open = _open_markets('clash_royale', cr_now)
    cr_hourly = dict(cr_open.filter(window='hourly').values_list('subject', 'pk'))
    cr = price_summary(Source.LIVE)
    moved = [r for r in cr['rows'] if r['direction'] in ('up', 'down')]
    for r in moved:
        r['market_pk'] = cr_hourly.get(r['snap'].card.name)
    # By price change, not percent: % has no value from a 0 price and exaggerates low-priced cards.
    risers = sorted((r for r in moved if r['direction'] == 'up'), key=lambda r: r['change'], reverse=True)
    fallers = sorted((r for r in moved if r['direction'] == 'down'), key=lambda r: r['change'])

    siege_now = clock.now('siege')
    siege_open = _open_markets('siege', siege_now)
    siege_cards = _cards(siege_open.filter(window='hourly'), siege_now)
    siege_movers = sorted(
        (c for c in siege_cards if c['change_pp']), key=lambda c: abs(c['change_pp']), reverse=True
    )[:5]

    return render(request, 'markets/dashboard.html', {
        'account': account,
        'positions_open': Position.objects.filter(account=account, market__status='open').count(),
        'cr': cr,
        'cr_clock': clock.mode('clash_royale'),
        'cr_now': cr_now,
        'cr_open_count': cr_open.count(),
        'cr_risers': risers[:5],
        'cr_fallers': fallers[:5],
        'siege_clock': clock.mode('siege'),
        'siege_now': siege_now,
        'siege_open_count': siege_open.count(),
        'siege_movers': siege_movers,
    })


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
        cards=_cards(markets.order_by('stat_kind', 'subject'), now),
        recent=Market.objects.filter(game=game, window=window, status__in=['settled', 'void'])
        .select_related('settlement')
        .order_by('-closes_at')[:8],
        cr_stale_since=stale_since(Source.LIVE) if game == 'clash_royale' else None,
    )
    template = 'markets/_market_grid.html' if request.headers.get('HX-Request') else 'markets/list.html'
    return render(request, template, ctx)


def market_detail(request, pk: int):
    market = get_object_or_404(Market, pk=pk)
    ctx = _header(request, market.game)
    card = _with_icons([_card(market, ctx['now'])])[0]
    points = list(market.trades.order_by('created_at', 'id').values_list('created_at', 'up_price_after'))
    ctx.update(
        card=card,
        chart=chart.price_chart(market.opens_at, market.closes_at, ctx['now'], points, card['up_price']),
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
