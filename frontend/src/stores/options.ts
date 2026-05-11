import { create } from 'zustand';
import { getExpiries } from '../api/client';

export type OptionCurrency = 'BTC' | 'ETH';

export interface ExpiryInfo {
  timestamp: number;
  expiry: string;
  daysToExpiry: number;
  atmIv: number;
}

interface OptionsState {
  currency: OptionCurrency;
  selectedExpiry: string;
  expiries: ExpiryInfo[];
  expiriesLoading: boolean;

  setCurrency: (c: OptionCurrency) => void;
  setSelectedExpiry: (e: string) => void;
  fetchExpiries: () => Promise<void>;
}

export const useOptionsStore = create<OptionsState>((set, get) => ({
  currency: 'BTC',
  selectedExpiry: '',
  expiries: [],
  expiriesLoading: false,

  setCurrency: (currency) => {
    set({ currency, selectedExpiry: '', expiries: [] });
    void get().fetchExpiries();
  },
  setSelectedExpiry: (selectedExpiry) => set({ selectedExpiry }),

  fetchExpiries: async () => {
    const { currency } = get();
    set({ expiriesLoading: true });
    try {
      const data = await getExpiries(currency);
      const now = Date.now();
      const mapped: ExpiryInfo[] = data.map((e: any) => ({
        timestamp: e.timestamp,
        expiry: e.expiry,
        daysToExpiry: Math.max(1, Math.round((e.timestamp - now) / 86400000)),
        atmIv: e.atm_iv ?? e.atmIv ?? 0,
      }));
      set({
        expiries: mapped,
        selectedExpiry: mapped.length > 0 ? String(mapped[0].timestamp) : '',
        expiriesLoading: false,
      });
    } catch {
      set({ expiries: [], expiriesLoading: false });
    }
  },
}));
