import { create } from 'zustand';

interface RefreshIntervals {
  dashboard: number;   // ms
  optionChain: number;
  orderbook: number;
  candles: number;
  equityCurve: number;
}

function computeIntervals(speed: number): RefreshIntervals {
  // speed: 0.0 (slow) → 1.0 (fast)
  // Interpolate between slow and fast presets
  const lerp = (slow: number, fast: number) =>
    Math.round(slow + (fast - slow) * speed);

  return {
    dashboard:   lerp(30000, 5000),   // 30s → 5s
    optionChain: lerp(30000, 5000),   // 30s → 5s
    orderbook:   lerp(5000,  1000),   // 5s  → 1s
    candles:     lerp(120000, 30000), // 2m  → 30s
    equityCurve: lerp(60000, 15000),  // 60s → 15s
  };
}

interface SettingsState {
  autoRefresh: boolean;
  speed: number; // 0.0 (slow) ~ 1.0 (fast)
  intervals: RefreshIntervals;

  setAutoRefresh: (on: boolean) => void;
  setSpeed: (speed: number) => void;
}

// Load from localStorage
const saved = (() => {
  try {
    const raw = localStorage.getItem('deribit-refresh-settings');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
})();

export const useSettingsStore = create<SettingsState>((set) => ({
  autoRefresh: saved?.autoRefresh ?? true,
  speed: saved?.speed ?? 0.5,
  intervals: computeIntervals(saved?.speed ?? 0.5),

  setAutoRefresh: (on) => {
    set({ autoRefresh: on });
    persistSettings({ autoRefresh: on });
  },

  setSpeed: (speed) => {
    const intervals = computeIntervals(speed);
    set({ speed, intervals });
    persistSettings({ speed });
  },
}));

function persistSettings(partial: Record<string, unknown>) {
  try {
    const current = JSON.parse(localStorage.getItem('deribit-refresh-settings') || '{}');
    localStorage.setItem('deribit-refresh-settings', JSON.stringify({ ...current, ...partial }));
  } catch { /* ignore */ }
}

export function getReadableIntervals(speed: number): Record<string, number> {
  const intervals = computeIntervals(speed);
  return {
    Dashboard: Math.round(intervals.dashboard / 1000),
    Options: Math.round(intervals.optionChain / 1000),
    OrderBook: Math.round(intervals.orderbook / 1000),
    Candles: Math.round(intervals.candles / 1000),
    Equity: Math.round(intervals.equityCurve / 1000),
  };
}

/** Hook: returns interval in ms, or null if auto-refresh is off */
export function useRefreshInterval(key: keyof RefreshIntervals): number | null {
  const autoRefresh = useSettingsStore((s) => s.autoRefresh);
  const interval = useSettingsStore((s) => s.intervals[key]);
  return autoRefresh ? interval : null;
}
