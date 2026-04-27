import { create } from 'zustand';
import type { Position, PortfolioSnapshot } from '../types/api';
import { getPortfolioSnapshot, getPositions } from '../api/client';

interface PortfolioState {
  equity: number;
  balance: number;
  unrealizedPnl: number;
  realizedPnl: number;
  positions: Position[];
  greeksSummary: {
    net_delta: number;
    net_gamma: number;
    net_theta: number;
    net_vega: number;
  };
  loading: boolean;
  error: string | null;

  fetchSnapshot: () => Promise<void>;
  updateFromWs: (data: Record<string, unknown>) => void;
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  equity: 0,
  balance: 0,
  unrealizedPnl: 0,
  realizedPnl: 0,
  positions: [],
  greeksSummary: { net_delta: 0, net_gamma: 0, net_theta: 0, net_vega: 0 },
  loading: false,
  error: null,

  fetchSnapshot: async () => {
    set({ loading: true, error: null });
    try {
      const snap = await getPortfolioSnapshot();
      set({
        equity: snap.equity,
        balance: snap.balance,
        unrealizedPnl: snap.unrealized_pnl,
        realizedPnl: snap.realized_pnl,
        positions: snap.positions,
        greeksSummary: snap.greeks_summary,
        loading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  updateFromWs: (data) => {
    set({
      equity: (data.equity as number) ?? 0,
      balance: (data.balance as number) ?? 0,
    });
  },
}));
