import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the API module BEFORE importing the store so the store picks up the spies.
vi.mock('../../src/api/accounts', () => ({
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
  activateAccount: vi.fn(),
  testCredentials: vi.fn(),
  testExistingAccount: vi.fn(),
}));

import * as accountsApi from '../../src/api/accounts';
import { useAccountsStore } from '../../src/stores/accounts';
import {
  switchChatPersistKey,
  migrateLegacyChatStore,
  useChatStore,
} from '../../src/stores/chat';

const mockedApi = vi.mocked(accountsApi);

function fakeAccount(over: Partial<accountsApi.AccountSummary> = {}): accountsApi.AccountSummary {
  return {
    id: 'acc-a',
    alias: 'A',
    endpoint: 'deribit_testnet',
    endpoint_label: 'test.deribit.com',
    is_production: false,
    client_id_tail: '1234',
    client_id: '',
    is_active: false,
    created_at: 0,
    last_used_at: null,
    ...over,
  };
}

describe('useAccountsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAccountsStore.setState({
      accounts: [],
      endpoints: [],
      activeId: null,
      loading: false,
      error: null,
    });
    localStorage.clear();
  });

  it('fetchAccounts populates accounts + endpoints + activeId', async () => {
    mockedApi.listAccounts.mockResolvedValue({
      accounts: [fakeAccount({ id: 'a' }), fakeAccount({ id: 'b', alias: 'B' })],
      active_id: 'a',
      endpoints: [
        { id: 'deribit_testnet', label: 'test.deribit.com', is_production: false },
      ],
    });

    await useAccountsStore.getState().fetchAccounts();
    const s = useAccountsStore.getState();
    expect(s.accounts).toHaveLength(2);
    expect(s.activeId).toBe('a');
    expect(s.endpoints).toHaveLength(1);
    expect(s.loading).toBe(false);
  });

  it('fetchAccounts records error on failure', async () => {
    mockedApi.listAccounts.mockRejectedValue(new Error('boom'));
    await useAccountsStore.getState().fetchAccounts();
    expect(useAccountsStore.getState().error).toBe('boom');
    expect(useAccountsStore.getState().loading).toBe(false);
  });

  it('activate sets activeId and refetches', async () => {
    mockedApi.activateAccount.mockResolvedValue({
      id: 'b',
      alias: 'B',
      endpoint: 'deribit_testnet',
      client_id: 'x',
      connected: true,
      authenticated: true,
    });
    mockedApi.listAccounts.mockResolvedValue({
      accounts: [fakeAccount({ id: 'b', alias: 'B', is_active: true })],
      active_id: 'b',
      endpoints: [],
    });

    await useAccountsStore.getState().activate('b');
    expect(useAccountsStore.getState().activeId).toBe('b');
    expect(mockedApi.listAccounts).toHaveBeenCalledTimes(1);
  });

  it('activate rolls back loading + records error on failure', async () => {
    mockedApi.activateAccount.mockRejectedValue(new Error('auth_failed'));
    await expect(useAccountsStore.getState().activate('b')).rejects.toThrow('auth_failed');
    expect(useAccountsStore.getState().loading).toBe(false);
    expect(useAccountsStore.getState().error).toBe('auth_failed');
  });
});

describe('chat store per-account persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    useChatStore.setState({
      open: false,
      messages: [],
      draft: '',
      pageContext: { route: '/' },
      tools: [],
      writeEnabled: false,
      loading: false,
      error: null,
    });
  });

  it('migrateLegacyChatStore renames chat-store to chat-store:<id>', () => {
    localStorage.setItem('chat-store', JSON.stringify({ state: { messages: [], writeEnabled: true } }));
    migrateLegacyChatStore('acc-A');
    expect(localStorage.getItem('chat-store')).toBeNull();
    expect(localStorage.getItem('chat-store:acc-A')).not.toBeNull();
  });

  it('migrateLegacyChatStore is a no-op when legacy key absent', () => {
    migrateLegacyChatStore('acc-A');
    expect(localStorage.getItem('chat-store:acc-A')).toBeNull();
  });

  it('switchChatPersistKey resets writeEnabled to false', async () => {
    useChatStore.setState({ writeEnabled: true });
    await switchChatPersistKey('acc-B');
    expect(useChatStore.getState().writeEnabled).toBe(false);
  });
});
