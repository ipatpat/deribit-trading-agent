import { describe, it, expect } from 'vitest';
import {
  OVERRIDE_DISPLAY,
  OVERRIDE_RANGES,
  overridesFromApi,
  overridesToApi,
  validateOverrides,
} from '../../src/utils/smartOrderValidation';

describe('overridesToApi', () => {
  it('converts timeout seconds → ms', () => {
    expect(overridesToApi({ timeout: 30 })).toEqual({ t_patience_ms: 30_000 });
  });

  it('converts priceLimitPct percentage → decimal', () => {
    expect(overridesToApi({ priceLimitPct: 0.3 })).toEqual({ price_limit_pct: 0.003 });
  });

  it('passes through ints unchanged', () => {
    expect(overridesToApi({ maxIocLevels: 2 })).toEqual({ max_cross_levels: 2 });
    expect(overridesToApi({ priceLimitTicks: 5 })).toEqual({ price_limit_ticks: 5 });
  });

  it('skips undefined and null', () => {
    expect(overridesToApi({})).toEqual({});
  });

  it('rounds float seconds to integer ms', () => {
    expect(overridesToApi({ timeout: 1.5 })).toEqual({ t_patience_ms: 1500 });
  });

  it('preserves prefer_maker boolean', () => {
    expect(overridesToApi({ prefer_maker: true })).toEqual({ prefer_maker: true });
  });
});

describe('overridesFromApi', () => {
  it('converts ms → seconds', () => {
    expect(overridesFromApi({ t_patience_ms: 30_000 })).toEqual({ timeout: 30 });
  });

  it('converts decimal → percentage', () => {
    expect(overridesFromApi({ price_limit_pct: 0.003 })).toEqual({ priceLimitPct: 0.3 });
  });

  it('handles unknown api fields gracefully', () => {
    expect(overridesFromApi({} as never)).toEqual({});
  });
});

describe('overridesToApi/FromApi roundtrip', () => {
  it('roundtrips timeout', () => {
    const round = overridesFromApi(overridesToApi({ timeout: 30 }));
    expect(round.timeout).toBeCloseTo(30, 6);
  });

  it('roundtrips priceLimitPct', () => {
    const round = overridesFromApi(overridesToApi({ priceLimitPct: 0.3 }));
    expect(round.priceLimitPct).toBeCloseTo(0.3, 6);
  });

  it('roundtrips full bundle', () => {
    const ui = {
      timeout: 45,
      maxIocLevels: 2,
      priceLimitPct: 0.5,
    };
    const round = overridesFromApi(overridesToApi(ui));
    expect(round.timeout).toBeCloseTo(45, 6);
    expect(round.maxIocLevels).toBe(2);
    expect(round.priceLimitPct).toBeCloseTo(0.5, 6);
  });
});

describe('OVERRIDE_DISPLAY default values map to API ranges', () => {
  it('timeout default 30s = 30_000ms within range', () => {
    const apiVal = OVERRIDE_DISPLAY.timeout.toApi(OVERRIDE_DISPLAY.timeout.displayDefault);
    expect(apiVal).toBe(OVERRIDE_RANGES.t_patience_ms.default);
  });

  it('priceLimitPct default 0.30% = 0.003 within range', () => {
    const apiVal = OVERRIDE_DISPLAY.priceLimitPct.toApi(
      OVERRIDE_DISPLAY.priceLimitPct.displayDefault,
    );
    expect(apiVal).toBeCloseTo(OVERRIDE_RANGES.price_limit_pct.default, 6);
  });

  it('display defaults pass validation as API values', () => {
    const ui = {
      timeout: OVERRIDE_DISPLAY.timeout.displayDefault,
      maxIocLevels: OVERRIDE_DISPLAY.maxIocLevels.displayDefault,
      priceLimitPct: OVERRIDE_DISPLAY.priceLimitPct.displayDefault,
    };
    const api = overridesToApi(ui);
    expect(validateOverrides(api)).toBeNull();
  });
});

describe('validateOverrides edge cases', () => {
  it('accepts boundary min', () => {
    expect(validateOverrides({ t_patience_ms: OVERRIDE_RANGES.t_patience_ms.min })).toBeNull();
  });

  it('accepts boundary max', () => {
    expect(validateOverrides({ t_patience_ms: OVERRIDE_RANGES.t_patience_ms.max })).toBeNull();
  });

  it('rejects below min', () => {
    expect(
      validateOverrides({ t_patience_ms: OVERRIDE_RANGES.t_patience_ms.min - 1 }),
    ).not.toBeNull();
  });

  it('rejects above max', () => {
    expect(
      validateOverrides({ t_patience_ms: OVERRIDE_RANGES.t_patience_ms.max + 1 }),
    ).not.toBeNull();
  });
});
