import { create } from 'zustand';
import {
  type AccountSummary,
  type EndpointInfo,
  type CreateAccountPayload,
  type UpdateAccountPayload,
  listAccounts,
  getActiveAccount,
  createAccount as apiCreate,
  updateAccount as apiUpdate,
  deleteAccount as apiDelete,
  activateAccount as apiActivate,
} from '../api/accounts';

interface AccountsState {
  accounts: AccountSummary[];
  endpoints: EndpointInfo[];
  activeId: string | null;
  loading: boolean;
  error: string | null;

  fetchAccounts: () => Promise<void>;
  /** Pulls the active account separately so the UI can show "connected" status. */
  fetchActive: () => Promise<{
    active: AccountSummary | null;
    connected: boolean;
    authenticated: boolean;
  }>;
  addAccount: (payload: CreateAccountPayload) => Promise<string>;
  updateAccount: (id: string, payload: UpdateAccountPayload) => Promise<void>;
  deleteAccount: (id: string) => Promise<void>;
  activate: (id: string) => Promise<void>;
}

export const useAccountsStore = create<AccountsState>((set, get) => ({
  accounts: [],
  endpoints: [],
  activeId: null,
  loading: false,
  error: null,

  fetchAccounts: async () => {
    set({ loading: true, error: null });
    try {
      const res = await listAccounts();
      set({
        accounts: res.accounts,
        endpoints: res.endpoints,
        activeId: res.active_id,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  fetchActive: async () => {
    try {
      const res = await getActiveAccount();
      if (res.active) {
        // Mirror to local activeId so subscribers can react.
        if (get().activeId !== res.active.id) {
          set({ activeId: res.active.id });
        }
        return {
          active: get().accounts.find((a) => a.id === res.active!.id) ?? null,
          connected: res.connected ?? false,
          authenticated: res.authenticated ?? false,
        };
      } else {
        if (get().activeId !== null) set({ activeId: null });
        return { active: null, connected: false, authenticated: false };
      }
    } catch (e) {
      set({ error: (e as Error).message });
      return { active: null, connected: false, authenticated: false };
    }
  },

  addAccount: async (payload) => {
    const res = await apiCreate(payload);
    await get().fetchAccounts();
    return res.id;
  },

  updateAccount: async (id, payload) => {
    await apiUpdate(id, payload);
    await get().fetchAccounts();
  },

  deleteAccount: async (id) => {
    await apiDelete(id);
    await get().fetchAccounts();
  },

  activate: async (id) => {
    set({ loading: true, error: null });
    try {
      await apiActivate(id);
      // The active flag flip is server-side; resync.
      set({ activeId: id, loading: false });
      await get().fetchAccounts();
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
      throw e;
    }
  },
}));

/**
 * Convenience selector: returns the currently-active account summary, or null.
 * Use this in components that need to render the active alias/endpoint without
 * threading activeId + accounts separately.
 */
export function selectActiveAccount(state: AccountsState): AccountSummary | null {
  if (!state.activeId) return null;
  return state.accounts.find((a) => a.id === state.activeId) ?? null;
}
