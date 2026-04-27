import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastStore {
  toasts: Toast[];
  show: (type: ToastType, message: string) => void;
  dismiss: (id: string) => void;
}

let counter = 0;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  show: (type, message) => {
    const id = `${Date.now()}-${++counter}`;
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, type, message }] }));
    const duration = type === 'error' ? 5000 : 3000;
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, duration);
  },
  dismiss: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));
