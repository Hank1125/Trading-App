import uuid
from datetime import timedelta
from fractions import Fraction

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from clashroyale.models import Card, CardMetricSnapshot, Source
from clashroyale.views import price_summary, stale_since
from markets import chart, clock, lmsr, providers, scheduler, services
from markets.models import Account, LedgerEntry, Market, Position, Trade


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
    # Rates (e.g. ban rate) display as %, prices as the value itself: a 17.49 card price is not "1749%".
    scale = 1 if m.stat_kind == 'card_price' else 100
    start_pct = scale * m.start_numerator / m.start_denominator
    if cur is _UNSET:
        cur = providers.value_at(m.game, m.stat_kind, m.subject, m.scope, min(now, m.closes_at))
    cur_pct = scale * float(cur.fraction) if cur else None
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


def _as_of(m: Market, now):
    return min(now, m.closes_at)  # the time _card reads a market's value at


def _clash_prices_by(markets: list[Market], now) -> dict:
    """providers.value_at for many Clash card-price markets: one query per (source, read time).

    Same rule as the provider: the card's latest snapshot with window_end <= as_of, where as_of is `now` for
    open markets and the close time for closed ones. Keyed by (source, card name, as_of).
    """
    groups: dict = {}
    for m in markets:
        if m.game == 'clash_royale' and m.stat_kind == 'card_price':
            groups.setdefault((m.scope.get('source', 'live'), _as_of(m, now)), []).append(m.subject)
    out = {}
    for (source, as_of), names in groups.items():
        snaps = (
            CardMetricSnapshot.objects.filter(card__name__in=names, source=source, window_end__lte=as_of)
            .order_by('card__name', '-window_end', '-id')
            .distinct('card__name')
            .select_related('card')
        )
        for snap in snaps:
            f = Fraction(snap.price)
            evidence = {'card_metric_snapshot_id': snap.pk, 'price': str(snap.price), 'as_of': snap.window_end.isoformat()}
            out[(source, snap.card.name, as_of)] = providers.StatPoint(f.numerator, f.denominator, evidence)
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
        key = (m.scope.get('source', 'live'), m.subject, _as_of(m, now))
        batched = m.game == 'clash_royale' and m.stat_kind == 'card_price'
        cards.append(_card(m, now, mode=modes[m.game], sides=sides, cur=prices.get(key) if batched else _UNSET))
    return _with_icons(cards)


def _with_icons(cards: list[dict]) -> list[dict]:
    """Attach each Clash card's icon URL (a market's subject is the card name)."""
    names = [c['m'].subject for c in cards if c['m'].game == 'clash_royale']
    icons = dict(Card.objects.filter(name__in=names).values_list('name', 'icon_url')) if names else {}
    for c in cards:
        c['icon'] = icons.get(c['m'].subject, '')
    return cards


GAME = Market.Game.CLASH_ROYALE  # the only game the app trades
HOT_WINDOW = timedelta(hours=1)
HOT_TOP = 5


def _header(request) -> dict:
    return {'account': _account(request), 'clock': clock.mode(GAME), 'now': clock.now(GAME)}


def _clash_market(pk: int) -> Market:
    return get_object_or_404(Market, pk=pk, game=GAME)


def _hot(now) -> dict:
    """The HOT_TOP cards with the most contracts traded in the last hour (any window), each with >= 1 trade."""
    rows = (
        Trade.objects.filter(market__game=GAME, created_at__gt=now - HOT_WINDOW, created_at__lte=now)
        .values('market__subject')
        .annotate(contracts=Sum('contracts'), trades=Count('id'))
        .order_by('-contracts', 'market__subject')[:HOT_TOP]
    )
    return {r['market__subject']: r for r in rows}


def _market_per_card(window: str, now) -> dict:
    """{card name: _card dict} for `window`: the card's open market, else its most recent one.

    Between :00 and ~:05 the new hourly markets wait for that hour's price snapshot; showing the market that
    just closed keeps each card's UP/DOWN split visible (marked closed) instead of an empty slot.
    """
    open_now = list(Market.objects.filter(game=GAME, window=window, opens_at__lte=now, closes_at__gt=now))
    latest = (
        Market.objects.filter(game=GAME, window=window, opens_at__lte=now)
        .exclude(subject__in=[m.subject for m in open_now])
        .select_related('settlement')
        .order_by('subject', '-opens_at')
        .distinct('subject')
    )
    return {c['m'].subject: c for c in _cards([*open_now, *latest], now)}


def _card_rows(window: str, now) -> tuple[dict, list[dict]]:
    """Price summary plus, for every card in the latest snapshot, its market for `window` and hot status."""
    summary = price_summary(Source.LIVE)
    markets = _market_per_card(window, now)
    hot = _hot(now)
    rows = []
    for r in summary['rows']:
        name = r['snap'].card.name
        m = markets.get(name)
        rows.append({**r, 'market': m, 'is_open': bool(m) and m['m'].status == Market.Status.OPEN and m['m'].closes_at > now,
                     'hot': hot.get(name)})  # fmt: skip
    return summary, rows


def _next_open(window: str, now):
    """When the current window's markets should appear: ~5 min after the window starts (cron writes prices at :05)."""
    return scheduler.window_start(window, now) + timedelta(minutes=5)


def dashboard(request):
    """Home: every Clash card with its price, hourly change and hourly market. The most-traded cards glow gold."""
    ctx = _header(request)
    now = ctx['now']
    summary, tiles = _card_rows('hourly', now)
    ctx.update(summary=summary, tiles=tiles, hot_count=sum(1 for t in tiles if t['hot']), hot_top=HOT_TOP,
               next_open=_next_open('hourly', now))  # fmt: skip
    template = 'markets/_dashboard_grid.html' if request.headers.get('HX-Request') else 'markets/dashboard.html'
    return render(request, template, ctx)


def market_list(request):
    window = request.GET.get('window', 'hourly')
    if window not in Market.Window.values:
        return HttpResponseBadRequest('unknown window')
    ctx = _header(request)
    now = ctx['now']
    summary, rows = _card_rows(window, now)
    recent = list(
        Market.objects.filter(game=GAME, window=window, status__in=['settled', 'void'])
        .select_related('settlement')
        .order_by('-closes_at')[:8]
    )
    for m in recent:
        s = getattr(m, 'settlement', None)
        m.start_value = m.start_numerator / m.start_denominator
        m.end_value = s.end_numerator / s.end_denominator if s and s.end_denominator else None
    ctx.update(
        window=window,
        summary=summary,
        rows=rows,
        open_count=sum(1 for r in rows if r['is_open']),
        next_open=_next_open(window, now),
        recent=recent,
        cr_stale_since=stale_since(Source.LIVE),
    )
    template = 'markets/_market_table.html' if request.headers.get('HX-Request') else 'markets/list.html'
    return render(request, template, ctx)


def market_detail(request, pk: int):
    market = _clash_market(pk)
    ctx = _header(request)
    card = _with_icons([_card(market, ctx['now'])])[0]
    points = list(market.trades.order_by('created_at', 'id').values_list('created_at', 'up_price_after'))
    ctx.update(
        card=card,
        card_api_id=Card.objects.filter(name=market.subject).values_list('api_id', flat=True).first(),
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
    market = _clash_market(pk)
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
    market = _clash_market(pk)
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
            now=clock.now(market.game),
        )
        ctx['trade'] = result.trade
    except services.TradeError as e:
        ctx['error'] = str(e)
        ctx['fresh_units'] = e.quote_units
    return render(request, 'markets/_trade_result.html', ctx)


def _sell_value_units(market: Market, position: Position) -> int | None:
    """What selling the whole position would return right now (exact LMSR proceeds), or None if not quotable."""
    try:
        return sum(
            services.quote_units(market, side, 'sell', n)
            for side, n in (('up', position.up_contracts), ('down', position.down_contracts))
            if n
        )
    except (services.TradeError, lmsr.LmsrError):
        return None


def portfolio(request):
    ctx = _header(request)
    account = ctx['account']
    positions = list(
        Position.objects.filter(account=account, market__game=GAME)
        .select_related('market', 'market__settlement')
        .order_by('-market__closes_at', '-id')
    )
    returned = dict(
        account.ledger.filter(kind__in=[LedgerEntry.Kind.PAYOUT, LedgerEntry.Kind.REFUND], market__isnull=False)
        .values('market_id')
        .annotate(total=Sum('delta_units'))
        .values_list('market_id', 'total')
    )
    icons = dict(Card.objects.filter(name__in={p.market.subject for p in positions}).values_list('name', 'icon_url'))
    active, history = [], []
    for p in positions:
        m = p.market
        row = {'p': p, 'm': m, 'icon': icons.get(m.subject, ''), 'cost': p.net_cost_units}
        if m.status == Market.Status.OPEN and (p.up_contracts or p.down_contracts):
            state = services.state_of(m)
            value = _sell_value_units(m, p)
            row.update(value=value, pnl=None if value is None else value - p.net_cost_units,
                       up_price=lmsr.display_price(state, 'up'), down_price=lmsr.display_price(state, 'down'))  # fmt: skip
            active.append(row)
        else:
            got = returned.get(m.pk, 0)
            row.update(value=got, pnl=got - p.net_cost_units, settlement=getattr(m, 'settlement', None))
            history.append(row)

    open_value = sum(r['value'] or 0 for r in active)
    open_cost = sum(r['cost'] for r in active)
    ctx.update(
        active=active,
        history=history,
        open_cost=open_cost,
        open_value=open_value,
        unrealized=open_value - open_cost,
        realized=sum(r['pnl'] for r in history),
        equity=account.balance_units + open_value,
        ledger=account.ledger.select_related('market').order_by('-created_at', '-id')[:30],
    )
    return render(request, 'markets/portfolio.html', ctx)


def account_page(request):
    """Who you are and what you hold. Name, budget and balance will come from the TrueMarket wallet."""
    ctx = _header(request)
    account = ctx['account']
    ctx.update(
        starting_units=account.ledger.filter(kind=LedgerEntry.Kind.GRANT).aggregate(t=Sum('delta_units'))['t'] or 0,
        trades_count=Trade.objects.filter(account=account).count(),
        open_positions=Position.objects.filter(account=account, market__game=GAME, market__status='open')
        .exclude(up_contracts=0, down_contracts=0)
        .count(),
    )
    return render(request, 'markets/account.html', ctx)


def wallet(request):
    """The separate True Markets wallet app (real Solana funds), embedded as a tab. Never linked to market stakes.

    Its dev server only answers on `localhost`, so this site must be opened via localhost too: then both share a
    site and the wallet's SameSite=Lax login cookie works inside the iframe.
    """
    ctx = _header(request)
    host, _, port = request.get_host().partition(':')
    ctx.update(
        wallet_url=settings.WALLET_URL,
        wrong_host=host != 'localhost',
        localhost_url=f"http://localhost{':' + port if port else ''}{request.get_full_path()}",
    )
    return render(request, 'markets/wallet.html', ctx)
