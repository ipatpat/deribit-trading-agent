export interface UnitStep {
  threshold: number;
  divisor: number;
  suffix: string;
}

export interface DecimalsBucket {
  rangeAtLeast: number;
  decimals: number;
}

export interface AxisFormatterOptions {
  prefix?: string;
  suffix?: string;
  unitSteps?: UnitStep[];
  decimalsBuckets?: DecimalsBucket[];
  fallbackDecimals?: number;
}

export interface AxisFormatter {
  format: (v: number) => string;
  divisor: number;
  unitSuffix: string;
  decimals: number;
}

const DEFAULT_UNIT_STEPS: UnitStep[] = [
  { threshold: 1_000_000, divisor: 1_000_000, suffix: 'M' },
  { threshold: 10_000, divisor: 1_000, suffix: 'k' },
];

const DEFAULT_DECIMALS_BUCKETS: DecimalsBucket[] = [
  { rangeAtLeast: 100, decimals: 0 },
  { rangeAtLeast: 10, decimals: 1 },
  { rangeAtLeast: 1, decimals: 2 },
  { rangeAtLeast: 0.1, decimals: 3 },
  { rangeAtLeast: 0, decimals: 4 },
];

export function pickAxisFormatter(
  values: number[],
  opts: AxisFormatterOptions = {},
): AxisFormatter {
  const prefix = opts.prefix ?? '';
  const suffix = opts.suffix ?? '';
  const unitSteps = opts.unitSteps ?? DEFAULT_UNIT_STEPS;
  const buckets = opts.decimalsBuckets ?? DEFAULT_DECIMALS_BUCKETS;
  const fallbackDecimals = opts.fallbackDecimals ?? 2;

  const finite = values.filter((v) => Number.isFinite(v));

  if (finite.length === 0) {
    return makeFormatter({
      prefix,
      suffix,
      divisor: 1,
      unitSuffix: '',
      decimals: fallbackDecimals,
    });
  }

  const maxAbs = finite.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
  const max = Math.max(...finite);
  const min = Math.min(...finite);
  const range = max - min;

  let divisor = 1;
  let unitSuffix = '';
  for (const step of unitSteps) {
    if (maxAbs >= step.threshold) {
      divisor = step.divisor;
      unitSuffix = step.suffix;
      break;
    }
  }

  let decimals = fallbackDecimals;
  if (range > 0) {
    const scaledRange = range / divisor;
    for (const bucket of buckets) {
      if (scaledRange >= bucket.rangeAtLeast) {
        decimals = bucket.decimals;
        break;
      }
    }
  }

  return makeFormatter({ prefix, suffix, divisor, unitSuffix, decimals });
}

interface MakeFormatterArgs {
  prefix: string;
  suffix: string;
  divisor: number;
  unitSuffix: string;
  decimals: number;
}

function makeFormatter({
  prefix,
  suffix,
  divisor,
  unitSuffix,
  decimals,
}: MakeFormatterArgs): AxisFormatter {
  return {
    divisor,
    unitSuffix,
    decimals,
    format: (v: number) => {
      if (!Number.isFinite(v)) return '';
      return `${prefix}${(v / divisor).toFixed(decimals)}${unitSuffix}${suffix}`;
    },
  };
}

export const USD_PRESET: AxisFormatterOptions = {
  prefix: '$',
};

export const BTC_PRESET: AxisFormatterOptions = {
  unitSteps: [],
  decimalsBuckets: [
    { rangeAtLeast: 0.1, decimals: 2 },
    { rangeAtLeast: 0.001, decimals: 4 },
    { rangeAtLeast: 0, decimals: 6 },
  ],
};

export const ETH_PRESET: AxisFormatterOptions = {
  unitSteps: [],
  decimalsBuckets: [
    { rangeAtLeast: 1, decimals: 1 },
    { rangeAtLeast: 0.01, decimals: 2 },
    { rangeAtLeast: 0, decimals: 4 },
  ],
};

export const IV_PRESET: AxisFormatterOptions = {
  suffix: '%',
  unitSteps: [],
};
