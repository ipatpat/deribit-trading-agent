export type EquityUnit = 'BTC' | 'ETH' | 'USD';

const FLAT_THRESHOLD: Record<EquityUnit, number> = {
  BTC: 0.001,
  ETH: 0.01,
  USD: 1e-6, // relative: range / max(|values|)
};

export interface FlatResult {
  flat: boolean;
  range: number;
  threshold: number;
  level: number; // representative midpoint when flat
}

export function computeEquityFlat(
  values: number[],
  unit: EquityUnit,
): FlatResult {
  if (values.length === 0) {
    return { flat: false, range: 0, threshold: 0, level: 0 };
  }
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { flat: false, range: 0, threshold: 0, level: 0 };
  }
  const range = max - min;
  const level = (max + min) / 2;
  let threshold: number;
  if (unit === 'USD') {
    const absMax = Math.max(Math.abs(max), Math.abs(min), 1);
    threshold = absMax * FLAT_THRESHOLD.USD;
  } else {
    threshold = FLAT_THRESHOLD[unit];
  }
  return {
    flat: range < threshold,
    range,
    threshold,
    level,
  };
}

export function isEquityFlat(values: number[], unit: EquityUnit): FlatResult {
  return computeEquityFlat(values, unit);
}
