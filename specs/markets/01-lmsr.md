# Markets 01 — LMSR market maker

Kalshi-style **UP / DOWN** markets on a stat over a time window (hourly, daily, weekly): will the stat end the window higher (UP) or lower (DOWN) than it started? Points are virtual only. This project is not affiliated with Kalshi.

Prices come from an automated market maker, so a trade always has a counterparty, even with a handful of demo users. The code is pure and has no ORM: `markets/lmsr.py`.

## Contracts
- A winning contract pays **100 points**. A losing one pays 0. If the window voids, everyone gets their net cost back (see the settlement spec).
- Users buy or sell **whole contracts**, 1 to 10,000 per trade.

## Pricing
With `q_up` and `q_down` contracts outstanding and liquidity `b`:

```
C(q)    = 100 * b * ln(e^(q_up/b) + e^(q_down/b))        # points
cost    = C(q after) - C(q before)                         # buy: trader pays
p_up    = e^(q_up/b) / (e^(q_up/b) + e^(q_down/b))         # shown as 1..99 points
```

- A new market starts at 50 / 50, and buying UP raises the UP price.
- Larger `b` means smaller price moves per contract.
- **Worst-case house loss** is `100 * b * ln 2` points (6,931.48 at `b = 100`).

## Money and rounding
- Integer units, with 1 point = 100 units.
- **Buys round up, sells round down**, so rounding never favors the trader, and buying then immediately selling never makes a profit.
- Math uses `Decimal` at 60 digits with log-sum-exp for stability.

## Worked example (`b = 100`, fresh market)
| Trade | Exact cost | Charged |
|---|---|---|
| Buy 1 UP | 50.1250 pts | **50.13** (5,013 units) |
| Buy 10 UP | 512.4947 pts | **512.50** (51,250 units) |

## Validation
- `side` must be `up` or `down`. Contract counts must be whole numbers in range; floats and bools are rejected.
- `b` must be a `Decimal` between 1 and 100,000.
- You can't sell more than is outstanding.
