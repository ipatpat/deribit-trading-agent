import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../src/api/accounts', () => ({
  listAccounts: vi.fn().mockResolvedValue({
    accounts: [],
    active_id: null,
    endpoints: [],
  }),
  getActiveAccount: vi.fn().mockResolvedValue({ active: null, connected: false, authenticated: false }),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
  activateAccount: vi.fn(),
  testCredentials: vi.fn(),
  testExistingAccount: vi.fn(),
}));

import AccountChip from '../../src/components/topbar/AccountChip';
import { useAccountsStore } from '../../src/stores/accounts';
import type { AccountSummary } from '../../src/api/accounts';

function seed(accounts: AccountSummary[], activeId: string | null) {
  useAccountsStore.setState({
    accounts,
    endpoints: [
      { id: 'deribit_testnet', label: 'test.deribit.com', is_production: false },
      { id: 'tibired_prod', label: 'tibired.com', is_production: true },
    ],
    activeId,
    loading: false,
    error: null,
  });
}

function acc(over: Partial<AccountSummary> = {}): AccountSummary {
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

function renderChip() {
  return render(
    <MemoryRouter>
      <AccountChip />
    </MemoryRouter>,
  );
}

describe('AccountChip', () => {
  beforeEach(() => {
    useAccountsStore.setState({ accounts: [], endpoints: [], activeId: null, loading: false, error: null });
  });

  it('shows orange Add-account CTA when no active account', () => {
    seed([], null);
    renderChip();
    expect(screen.getByText(/add account/i)).toBeTruthy();
  });

  it('shows alias and endpoint when an account is active', () => {
    seed([acc({ id: 'a', alias: 'main', is_active: true })], 'a');
    renderChip();
    expect(screen.getByText('main')).toBeTruthy();
  });

  it('toggling chip reveals dropdown with the other accounts under "Switch to"', () => {
    seed(
      [
        acc({ id: 'a', alias: 'A', is_active: true }),
        acc({ id: 'b', alias: 'B' }),
        acc({ id: 'c', alias: 'C', is_production: true, endpoint: 'tibired_prod' }),
      ],
      'a',
    );
    renderChip();
    fireEvent.click(screen.getByRole('button', { name: /A/ }));
    expect(screen.getByText(/switch to/i)).toBeTruthy();
    expect(screen.getByText('B')).toBeTruthy();
    expect(screen.getByText('C')).toBeTruthy();
  });

  it('Paper Trade tag appears for non-production accounts (Live is default, no tag)', () => {
    seed(
      [
        acc({ id: 'p', alias: 'prod', is_production: true, endpoint: 'tibired_prod', is_active: true }),
        acc({ id: 't', alias: 'paper', is_production: false, endpoint: 'deribit_testnet' }),
      ],
      'p',
    );
    renderChip();
    // Closed chip on production: no Paper tag, no Live tag.
    expect(screen.queryByText(/paper/i)).toBeNull();
    expect(screen.queryByText(/^live$/i)).toBeNull();
    // Open dropdown — Paper Trade label appears on the testnet row.
    fireEvent.click(screen.getByRole('button', { name: /prod/ }));
    expect(screen.getAllByText(/paper trade/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^live$/i)).toBeNull();
  });
});
