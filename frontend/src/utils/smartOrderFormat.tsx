import type { SmartOrder, SmartOrderIntent } from '../types/api';

const TAKER_BPS = 5;
const MAKER_BPS = 1;

const OPTION_RE = /^[A-Z]+-\d{1,2}[A-Z]{3}\d{2}-\d+(?:\.\d+)?-(C|P)$/;

export function getInstrumentCurrency(instrument: string): 'BTC' | 'ETH' | null {
  if (instrument.startsWith('BTC')) return 'BTC';
  if (instrument.startsWith('ETH')) return 'ETH';
  return null;
}

export function contractFaceUsd(
  instrument: string,
  indexPrices: Record<string, number> | null | undefined,
): number | null {
  if (instrument === 'BTC-PERPETUAL') return 10;
  if (instrument === 'ETH-PERPETUAL') return 1;
  if (OPTION_RE.test(instrument)) {
    const cur = getInstrumentCurrency(instrument);
    if (!cur) return null;
    const idx = indexPrices?.[cur];
    return idx && Number.isFinite(idx) && idx > 0 ? idx : null;
  }
  return null;
}

export function feeSavedUsd(
  order: SmartOrder,
  indexPrices: Record<string, number> | null | undefined,
): number | null {
  if (order.fee_mode !== 'maker') return 0;
  if (order.filled_amount <= 0) return 0;
  const face = contractFaceUsd(order.instrument, indexPrices);
  if (face === null) return null;
  return ((TAKER_BPS - MAKER_BPS) / 10_000) * order.filled_amount * face;
}

export const LEVEL_COLORS: Record<number, string> = {
  0: 'bg-cream-dark text-secondary',
  1: 'bg-blue-100 text-blue-800',
  2: 'bg-yellow-100 text-yellow-800',
  3: 'bg-orange-100 text-orange-800',
  4: 'bg-loss-bg text-loss',
};

export const INTENT_COLORS: Record<string, string> = {
  standard: 'bg-cream-dark text-secondary',
  urgent: 'bg-loss-bg text-loss',
  legacy: 'bg-divider text-secondary',
};

export function LevelBadge({ level }: { level: number }) {
  const cls = LEVEL_COLORS[level] ?? LEVEL_COLORS[0];
  return (
    <span
      className={`inline-flex items-center justify-center px-1.5 py-0.5 rounded text-[10px] font-bold w-10 ${cls}`}
    >
      Lv{level}
    </span>
  );
}

export function IntentBadge({ intent }: { intent: SmartOrderIntent | null }) {
  const key = intent ?? 'legacy';
  const cls = INTENT_COLORS[key] ?? INTENT_COLORS.legacy;
  const label = intent === 'urgent' ? 'Urgent' : intent === 'standard' ? 'Standard' : 'Legacy';
  return (
    <span
      className={`inline-flex items-center justify-center px-1.5 py-0.5 rounded text-[10px] font-bold w-16 ${cls}`}
    >
      {label}
    </span>
  );
}
