import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../src/api/accounts', () => ({
  activateAccount: vi.fn().mockResolvedValue({}),
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
  testCredentials: vi.fn(),
  testExistingAccount: vi.fn(),
}));

import SwitchAccountModal from '../../src/components/account/SwitchAccountModal';
import { useAccountsStore } from '../../src/stores/accounts';
import { useSmartOrdersStore } from '../../src/stores/smartOrders';
import { useChatStore } from '../../src/stores/chat';
import type { AccountSummary } from '../../src/api/accounts';

function acc(over: Partial<AccountSummary> = {}): AccountSummary {
  return {
    id: 'b',
    alias: 'target',
    endpoint: 'tibired_prod',
    endpoint_label: 'tibired.com',
    is_production: true,
    client_id_tail: '4321',
    client_id: '',
    is_active: false,
    created_at: 0,
    last_used_at: null,
    ...over,
  };
}

describe('SwitchAccountModal', () => {
  beforeEach(() => {
    useAccountsStore.setState({
      accounts: [acc({ id: 'a', alias: 'current', is_active: true, is_production: false, endpoint: 'deribit_testnet', endpoint_label: 'test.deribit.com' })],
      endpoints: [],
      activeId: 'a',
      loading: false,
      error: null,
    });
    useSmartOrdersStore.setState({ orders: [], loading: false, error: null });
    useChatStore.setState({
      open: false, messages: [], draft: '', pageContext: { route: '/' },
      tools: [], writeEnabled: false, loading: false, error: null,
    });
  });

  it('renders nothing when target is null', () => {
    const { container } = render(<SwitchAccountModal target={null} currentId="a" onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows production warning when target is_production', () => {
    render(<SwitchAccountModal target={acc()} currentId="a" onClose={() => {}} />);
    expect(screen.getByText(/production account/i)).toBeTruthy();
    expect(screen.getByText(/real funds/i)).toBeTruthy();
  });

  it('shows smart-orders warning with count when in-flight orders exist', () => {
    useSmartOrdersStore.setState({
      orders: [
        // @ts-expect-error partial test fixture
        { id: 's1', state: 'live' },
        // @ts-expect-error partial test fixture
        { id: 's2', state: 'live' },
        // @ts-expect-error partial test fixture
        { id: 's3', state: 'filled' }, // terminal — excluded
      ],
      loading: false,
      error: null,
    });
    render(<SwitchAccountModal target={acc()} currentId="a" onClose={() => {}} />);
    expect(screen.getByText(/2/)).toBeTruthy();
    expect(screen.getByText(/in-flight smart order/i)).toBeTruthy();
  });

  it('Cancel button calls onClose', () => {
    const onClose = vi.fn();
    render(<SwitchAccountModal target={acc()} currentId="a" onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('Switch button triggers activate', async () => {
    const onClose = vi.fn();
    render(<SwitchAccountModal target={acc()} currentId="a" onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /switch to "target"/i }));
    // activate runs through the mocked api; no assertion on store side-effect
    // needed — we just confirm no crash + the modal closes after success.
    await new Promise((r) => setTimeout(r, 10));
    expect(onClose).toHaveBeenCalled();
  });

  it('writeEnabled warning shown when chat write mode is armed', () => {
    useChatStore.setState({ writeEnabled: true });
    render(<SwitchAccountModal target={acc()} currentId="a" onClose={() => {}} />);
    expect(screen.getByText(/read only/i)).toBeTruthy();
  });
});
