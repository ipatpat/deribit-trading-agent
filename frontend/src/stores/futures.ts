import { create } from 'zustand';

export const FUTURES_INSTRUMENTS = ['BTC-PERPETUAL', 'ETH-PERPETUAL'] as const;
export type FuturesInstrument = (typeof FUTURES_INSTRUMENTS)[number];

interface FuturesState {
  selectedInstrument: FuturesInstrument;
  setSelectedInstrument: (i: FuturesInstrument) => void;
}

export const useFuturesStore = create<FuturesState>((set) => ({
  selectedInstrument: 'BTC-PERPETUAL',
  setSelectedInstrument: (selectedInstrument) => set({ selectedInstrument }),
}));
