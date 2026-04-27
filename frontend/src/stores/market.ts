import { create } from 'zustand';
import type { Ticker } from '../types/api';

interface MarketState {
  tickers: Map<string, Ticker>;
  activeInstrument: string | null;

  /** Set or update a single ticker (usually from WS). */
  setTicker: (ticker: Ticker) => void;

  /** Bulk-set tickers. */
  setTickers: (tickers: Ticker[]) => void;

  /** Change the currently active instrument. */
  setActiveInstrument: (instrument: string | null) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  tickers: new Map(),
  activeInstrument: null,

  setTicker: (ticker) =>
    set((state) => {
      const next = new Map(state.tickers);
      next.set(ticker.instrument_name, ticker);
      return { tickers: next };
    }),

  setTickers: (tickers) =>
    set(() => {
      const map = new Map<string, Ticker>();
      tickers.forEach((t) => map.set(t.instrument_name, t));
      return { tickers: map };
    }),

  setActiveInstrument: (instrument) => set({ activeInstrument: instrument }),
}));
