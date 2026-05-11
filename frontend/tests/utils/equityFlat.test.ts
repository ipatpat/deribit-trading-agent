import { describe, it, expect } from 'vitest';
import { computeEquityFlat } from '../../src/utils/equityFlat';

describe('computeEquityFlat — BTC', () => {
  it('flags as flat when range < 0.001 BTC', () => {
    // 99.999907 / 99.999906 / 99.999905 — range ~1e-6 BTC → flat
    const result = computeEquityFlat([99.999907, 99.999906, 99.999905], 'BTC');
    expect(result.flat).toBe(true);
    expect(result.range).toBeLessThan(0.001);
  });

  it('not flat when range > 0.001 BTC', () => {
    const result = computeEquityFlat([99.5, 99.7, 99.9, 100.1], 'BTC');
    expect(result.flat).toBe(false);
  });

  it('returns level near midpoint when flat', () => {
    const result = computeEquityFlat([99.999, 100.0, 100.001], 'BTC');
    expect(result.level).toBeCloseTo(100, 4);
  });
});

describe('computeEquityFlat — ETH', () => {
  it('flags flat when range < 0.01 ETH', () => {
    const result = computeEquityFlat([10.001, 10.002, 10.003], 'ETH');
    expect(result.flat).toBe(true);
  });

  it('not flat when range > 0.01 ETH', () => {
    const result = computeEquityFlat([10.0, 10.5, 11.0], 'ETH');
    expect(result.flat).toBe(false);
  });
});

describe('computeEquityFlat — USD relative threshold', () => {
  it('not flat when range >> 1e-6 of max', () => {
    // $5,000 ± $50 → range = 100, threshold = 5050 × 1e-6 ≈ 0.005 → not flat
    const result = computeEquityFlat([5_000, 4_950, 5_050, 5_000], 'USD');
    expect(result.flat).toBe(false);
  });

  it('flags flat for genuinely tight USD series', () => {
    // $100,000 with 1¢ noise → range = 0.01, threshold = 0.1 → flat
    const result = computeEquityFlat(
      [100_000.0, 100_000.01, 100_000.0, 99_999.99],
      'USD',
    );
    expect(result.flat).toBe(true);
  });

  it('not flat with normal USD volatility', () => {
    const result = computeEquityFlat([5_000, 5_500, 4_800, 5_200], 'USD');
    expect(result.flat).toBe(false);
  });
});

describe('computeEquityFlat — empty / degenerate', () => {
  it('empty array is not flat', () => {
    const result = computeEquityFlat([], 'BTC');
    expect(result.flat).toBe(false);
  });

  it('single point — range 0 → flat', () => {
    const result = computeEquityFlat([100], 'BTC');
    expect(result.flat).toBe(true);
    expect(result.range).toBe(0);
  });
});
