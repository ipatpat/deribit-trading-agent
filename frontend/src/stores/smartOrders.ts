import { create } from 'zustand';
import type { SmartOrder } from '../types/api';
import { getSmartOrders } from '../api/client';

interface SmartOrdersState {
  orders: SmartOrder[];
  loading: boolean;
  error: string | null;

  /** Fetch all smart orders from the API. */
  fetchOrders: () => Promise<void>;

  /** Add a single order (e.g. from WS). */
  addOrder: (order: SmartOrder) => void;

  /** Update an existing order by id. */
  updateOrder: (order: SmartOrder) => void;

  /** Remove an order by id. */
  removeOrder: (id: string) => void;
}

export const useSmartOrdersStore = create<SmartOrdersState>((set) => ({
  orders: [],
  loading: false,
  error: null,

  fetchOrders: async () => {
    set({ loading: true, error: null });
    try {
      const orders = await getSmartOrders();
      set({ orders, loading: false });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  addOrder: (order) =>
    set((state) => ({ orders: [...state.orders, order] })),

  updateOrder: (order) =>
    set((state) => ({
      orders: state.orders.map((o) => (o.id === order.id ? order : o)),
    })),

  removeOrder: (id) =>
    set((state) => ({
      orders: state.orders.filter((o) => o.id !== id),
    })),
}));
