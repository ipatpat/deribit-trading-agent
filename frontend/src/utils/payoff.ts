export interface OptionLeg {
  strike: number;
  premium: number;
  type: 'call' | 'put';
  direction: 'buy' | 'sell';
  amount: number;
}

export interface PayoffPoint {
  price: number;
  pnl: number;
}

/**
 * Calculate the payoff curve for a set of option legs.
 * Returns an array of {price, pnl} points suitable for ECharts.
 *
 * @param legs  Array of option legs
 * @param min   Lower bound of price range (defaults to 0.5x lowest strike)
 * @param max   Upper bound of price range (defaults to 1.5x highest strike)
 * @param steps Number of points to compute (default 200)
 */
export function calculatePayoff(
  legs: OptionLeg[],
  min?: number,
  max?: number,
  steps = 200,
): PayoffPoint[] {
  if (legs.length === 0) return [];

  const strikes = legs.map((l) => l.strike);
  const lo = min ?? Math.min(...strikes) * 0.5;
  const hi = max ?? Math.max(...strikes) * 1.5;
  const step = (hi - lo) / steps;

  const points: PayoffPoint[] = [];

  for (let i = 0; i <= steps; i++) {
    const price = lo + step * i;
    let pnl = 0;

    for (const leg of legs) {
      const sign = leg.direction === 'buy' ? 1 : -1;
      let intrinsic: number;

      if (leg.type === 'call') {
        intrinsic = Math.max(price - leg.strike, 0);
      } else {
        intrinsic = Math.max(leg.strike - price, 0);
      }

      pnl += sign * (intrinsic - leg.premium) * leg.amount;
    }

    points.push({ price: Math.round(price * 100) / 100, pnl: Math.round(pnl * 100) / 100 });
  }

  return points;
}
