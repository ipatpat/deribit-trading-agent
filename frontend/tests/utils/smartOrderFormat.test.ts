import { describe, it, expect } from 'vitest';
import {
  contractFaceUsd,
  feeSavedUsd,
  getInstrumentCurrency,
} from '../../src/utils/smartOrderFormat';
import type { SmartOrder } from '../../src/types/api';

const INDEX = { BTC: 60_000, ETH: 3_000 };

function makeOrder(overrides: Partial<SmartOrder> = {}): SmartOrder {
  return {
    id: 'so-1',
    instrument: 'BTC-PERPETUAL',
    direction: 'buy',
    amount: 100,
    intent: 'standard',
    algorithm: 'intent:standard',
    state: 'completed',
    deribit_order_id: 'd-1',
    current_price: 60_000,
    current_level: 0,
    filled_amount: 100,
    amend_count: 0,
    post_only_reject_count: 0,
    elapsed_ms: 1_000,
    t_patience_ms: 30_000,
    fee_mode: 'maker',
    ...overrides,
  };
}

describe('getInstrumentCurrency', () => {
  it('detects BTC', () => {
    expect(getInstrumentCurrency('BTC-PERPETUAL')).toBe('BTC');
    expect(getInstrumentCurrency('BTC-30MAY26-100000-C')).toBe('BTC');
  });
  it('detects ETH', () => {
    expect(getInstrumentCurrency('ETH-PERPETUAL')).toBe('ETH');
  });
  it('returns null for unknown', () => {
    expect(getInstrumentCurrency('SOL-PERPETUAL')).toBeNull();
  });
});

describe('contractFaceUsd', () => {
  it('BTC-PERPETUAL is $10', () => {
    expect(contractFaceUsd('BTC-PERPETUAL', INDEX)).toBe(10);
  });
  it('ETH-PERPETUAL is $1', () => {
    expect(contractFaceUsd('ETH-PERPETUAL', INDEX)).toBe(1);
  });
  it('BTC option uses BTC index', () => {
    expect(contractFaceUsd('BTC-30MAY26-100000-C', INDEX)).toBe(60_000);
  });
  it('ETH option uses ETH index', () => {
    expect(contractFaceUsd('ETH-30MAY26-3000-P', INDEX)).toBe(3_000);
  });
  it('option with missing index returns null', () => {
    expect(contractFaceUsd('BTC-30MAY26-100000-C', {})).toBeNull();
    expect(contractFaceUsd('BTC-30MAY26-100000-C', null)).toBeNull();
  });
  it('unknown instrument returns null', () => {
    expect(contractFaceUsd('SOL-PERPETUAL', INDEX)).toBeNull();
    expect(contractFaceUsd('FOO-BAR', INDEX)).toBeNull();
  });
});

describe('feeSavedUsd', () => {
  it('BTC perp maker: 4bps × 100 contracts × $10 = $0.40', () => {
    const order = makeOrder({ instrument: 'BTC-PERPETUAL', filled_amount: 100, fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBeCloseTo(0.4, 6);
  });

  it('BTC perp maker, 10 contracts: $0.04 ballpark', () => {
    const order = makeOrder({ instrument: 'BTC-PERPETUAL', filled_amount: 10, fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBeCloseTo(0.04, 6);
  });

  it('ETH perp maker: 4bps × 100 contracts × $1 = $0.04', () => {
    const order = makeOrder({ instrument: 'ETH-PERPETUAL', filled_amount: 100, fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBeCloseTo(0.04, 6);
  });

  it('option maker uses index price', () => {
    // BTC option, filled 1, index 60000 → 4bps × 1 × 60000 = $24
    const order = makeOrder({ instrument: 'BTC-30MAY26-100000-C', filled_amount: 1, fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBeCloseTo(24, 4);
  });

  it('fee_mode = taker returns 0', () => {
    const order = makeOrder({ fee_mode: 'taker' });
    expect(feeSavedUsd(order, INDEX)).toBe(0);
  });

  it('fee_mode = null returns 0', () => {
    const order = makeOrder({ fee_mode: null });
    expect(feeSavedUsd(order, INDEX)).toBe(0);
  });

  it('fee_mode = "any" returns 0', () => {
    const order = makeOrder({ fee_mode: 'any' });
    expect(feeSavedUsd(order, INDEX)).toBe(0);
  });

  it('unknown instrument with maker returns null', () => {
    const order = makeOrder({ instrument: 'SOL-PERPETUAL', fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBeNull();
  });

  it('option maker with missing index returns null', () => {
    const order = makeOrder({ instrument: 'BTC-30MAY26-100000-C', fee_mode: 'maker', filled_amount: 1 });
    expect(feeSavedUsd(order, {})).toBeNull();
  });

  it('zero filled_amount returns 0 even with maker', () => {
    const order = makeOrder({ filled_amount: 0, fee_mode: 'maker' });
    expect(feeSavedUsd(order, INDEX)).toBe(0);
  });
});
