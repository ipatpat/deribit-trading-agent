import type { SmartOrderOverrides } from '../api/client';

export interface OverrideRanges {
  t_patience_ms: { min: number; max: number; default: number };
  max_cross_levels: { min: number; max: number; default: number };
  price_limit_pct: { min: number; max: number; default: number };
  price_limit_ticks: { min: number; max: number; default: number };
  price_limit_iv: { min: number; max: number; default: number };
}

export const OVERRIDE_RANGES: OverrideRanges = {
  t_patience_ms: { min: 1_000, max: 600_000, default: 30_000 },
  max_cross_levels: { min: 1, max: 5, default: 1 },
  price_limit_pct: { min: 0.0001, max: 0.05, default: 0.003 },
  price_limit_ticks: { min: 1, max: 100, default: 5 },
  price_limit_iv: { min: 0.001, max: 0.2, default: 0.02 },
};

/**
 * UI ↔ API value conversion. Each entry maps an internal API field to the
 * user-facing label, unit, tooltip, and display range. `toApi`/`fromApi`
 * convert between the UI value (what the user types) and the wire value.
 */
export interface OverrideDisplayEntry {
  apiField: keyof SmartOrderOverrides;
  label: string;
  unit: string;
  tooltip: string;
  displayMin: number;
  displayMax: number;
  displayDefault: number;
  step?: string;
  toApi: (uiValue: number) => number;
  fromApi: (apiValue: number) => number;
}

export const OVERRIDE_DISPLAY: Record<string, OverrideDisplayEntry> = {
  timeout: {
    apiField: 't_patience_ms',
    label: 'Timeout',
    unit: 's',
    tooltip:
      'How long the order works before fully escalating to market (default 30s)',
    displayMin: 1,
    displayMax: 600,
    displayDefault: 30,
    toApi: (v) => Math.round(v * 1000),
    fromApi: (v) => v / 1000,
  },
  maxIocLevels: {
    apiField: 'max_cross_levels',
    label: 'Max IOC Levels',
    unit: '',
    tooltip:
      'Maximum order-book levels to sweep with IOC before falling back to market (default 1)',
    displayMin: 1,
    displayMax: 5,
    displayDefault: 1,
    toApi: (v) => Math.round(v),
    fromApi: (v) => v,
  },
  priceLimitPct: {
    apiField: 'price_limit_pct',
    label: 'Price Limit',
    unit: '%',
    tooltip:
      'Hard price cap relative to mid (default 0.30%). Order will not chase past this distance.',
    displayMin: 0.01,
    displayMax: 5,
    displayDefault: 0.3,
    step: '0.05',
    toApi: (v) => v / 100,
    fromApi: (v) => v * 100,
  },
  priceLimitTicks: {
    apiField: 'price_limit_ticks',
    label: 'Price Limit (Ticks)',
    unit: 'ticks',
    tooltip:
      'For options: hard cap in ticks from mid (default 5). Order will not cross past this many ticks.',
    displayMin: 1,
    displayMax: 100,
    displayDefault: 5,
    toApi: (v) => Math.round(v),
    fromApi: (v) => v,
  },
  priceLimitIv: {
    apiField: 'price_limit_iv',
    label: 'IV Limit',
    unit: 'vols',
    tooltip:
      'For options (BS): hard cap in vol points beyond mid IV (default 0.02). Hidden when BS unavailable.',
    displayMin: 0.001,
    displayMax: 0.2,
    displayDefault: 0.02,
    step: '0.005',
    toApi: (v) => v,
    fromApi: (v) => v,
  },
};

const API_TO_UI_KEY: Record<string, string> = Object.fromEntries(
  Object.entries(OVERRIDE_DISPLAY).map(([uiKey, entry]) => [entry.apiField, uiKey]),
);

export type UiOverrides = Partial<{
  timeout: number;
  maxIocLevels: number;
  priceLimitPct: number;
  priceLimitTicks: number;
  priceLimitIv: number;
  prefer_maker: boolean;
}>;

export function overridesToApi(ui: UiOverrides): SmartOrderOverrides {
  const out: SmartOrderOverrides = {};
  for (const [uiKey, value] of Object.entries(ui)) {
    if (value === undefined || value === null) continue;
    if (uiKey === 'prefer_maker') {
      out.prefer_maker = Boolean(value);
      continue;
    }
    const entry = OVERRIDE_DISPLAY[uiKey];
    if (!entry) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    (out as Record<string, number>)[entry.apiField] = entry.toApi(value);
  }
  return out;
}

export function overridesFromApi(api: SmartOrderOverrides): UiOverrides {
  const out: UiOverrides = {};
  for (const [apiKey, value] of Object.entries(api)) {
    if (value === undefined || value === null) continue;
    if (apiKey === 'prefer_maker') {
      out.prefer_maker = Boolean(value);
      continue;
    }
    const uiKey = API_TO_UI_KEY[apiKey];
    if (!uiKey) continue;
    const entry = OVERRIDE_DISPLAY[uiKey];
    if (!entry) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    (out as Record<string, number>)[uiKey] = entry.fromApi(value);
  }
  return out;
}

export function validateOverrides(
  overrides: SmartOrderOverrides,
): string | null {
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined || value === null) continue;
    if (key === 'prefer_maker') continue;
    const range = OVERRIDE_RANGES[key as keyof OverrideRanges];
    if (!range) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return `${key} must be a number`;
    }
    if (value < range.min || value > range.max) {
      return `${key} must be in [${range.min}, ${range.max}]`;
    }
  }
  return null;
}

export function isOptionInstrument(instrument: string): boolean {
  return /-(C|P)$/.test(instrument);
}
