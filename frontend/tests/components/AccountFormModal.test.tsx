import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../src/api/accounts', () => ({
  testCredentials: vi.fn().mockResolvedValue({ ok: true, ws_url: 'wss://test' }),
  testExistingAccount: vi.fn().mockResolvedValue({ ok: true }),
  createAccount: vi.fn().mockResolvedValue({ id: 'new-id', alias: 'x', endpoint: 'deribit_testnet', client_id_tail: '0000' }),
  updateAccount: vi.fn().mockResolvedValue({ status: 'updated', id: 'a' }),
  listAccounts: vi.fn().mockResolvedValue({ accounts: [], active_id: null, endpoints: [] }),
  deleteAccount: vi.fn(),
  activateAccount: vi.fn(),
  getActiveAccount: vi.fn(),
}));

import * as accountsApi from '../../src/api/accounts';
import AccountFormModal from '../../src/components/account/AccountFormModal';
import { useAccountsStore } from '../../src/stores/accounts';
import type { AccountSummary, EndpointInfo } from '../../src/api/accounts';

const mockedApi = vi.mocked(accountsApi);

const ENDPOINTS: EndpointInfo[] = [
  { id: 'deribit_testnet', label: 'test.deribit.com', is_production: false },
  { id: 'tibired_prod', label: 'tibired.com', is_production: true },
];

function fakeAccount(over: Partial<AccountSummary> = {}): AccountSummary {
  return {
    id: 'a',
    alias: 'main',
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

describe('AccountFormModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAccountsStore.setState({ accounts: [], endpoints: ENDPOINTS, activeId: null, loading: false, error: null });
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <AccountFormModal open={false} endpoints={ENDPOINTS} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('create mode: shows endpoint radios and Create button', () => {
    render(<AccountFormModal open endpoints={ENDPOINTS} onClose={() => {}} />);
    expect(screen.getByText(/add account/i)).toBeTruthy();
    expect(screen.getByText(/test\.deribit\.com/)).toBeTruthy();
    expect(screen.getByText(/tibired\.com/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /^create$/i })).toBeTruthy();
  });

  it('edit mode: endpoint + client_id are disabled and Save button shown', () => {
    render(<AccountFormModal open account={fakeAccount()} endpoints={ENDPOINTS} onClose={() => {}} />);
    expect(screen.getByText(/edit "main"/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /^save$/i })).toBeTruthy();
    expect(screen.getByText(/endpoint is locked/i)).toBeTruthy();
    expect(screen.getByText(/client id is locked/i)).toBeTruthy();
  });

  it('Test connection (create mode) calls testCredentials with form values', async () => {
    render(<AccountFormModal open endpoints={ENDPOINTS} onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/enter client id/i), { target: { value: 'cid' } });
    fireEvent.change(screen.getByPlaceholderText(/enter client secret/i), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }));
    await new Promise((r) => setTimeout(r, 10));
    expect(mockedApi.testCredentials).toHaveBeenCalledWith({
      endpoint: 'deribit_testnet',
      client_id: 'cid',
      client_secret: 'secret',
    });
  });

  it('Test connection (edit mode without new secret) tests existing account', async () => {
    render(<AccountFormModal open account={fakeAccount()} endpoints={ENDPOINTS} onClose={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }));
    await new Promise((r) => setTimeout(r, 10));
    expect(mockedApi.testExistingAccount).toHaveBeenCalledWith('a');
  });

  it('endpoint radio updates selection in create mode', () => {
    render(<AccountFormModal open endpoints={ENDPOINTS} onClose={() => {}} />);
    const tibiredRadio = screen.getByLabelText(/tibired\.com/i);
    fireEvent.click(tibiredRadio);
    expect((tibiredRadio as HTMLInputElement).checked).toBe(true);
  });
});
