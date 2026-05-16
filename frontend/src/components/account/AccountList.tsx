import { useEffect, useState } from 'react';
import { Edit2, Trash2, Plus, CheckCircle2 } from 'lucide-react';
import { useAccountsStore } from '../../stores/accounts';
import { useToastStore } from '../../stores/toast';
import { type AccountSummary } from '../../api/accounts';
import AccountFormModal from './AccountFormModal';
import SwitchAccountModal from './SwitchAccountModal';

function AccountList() {
  const { accounts, endpoints, activeId, loading, fetchAccounts, deleteAccount } = useAccountsStore();
  const showToast = useToastStore((s) => s.show);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AccountSummary | null>(null);
  const [switchTarget, setSwitchTarget] = useState<AccountSummary | null>(null);

  useEffect(() => {
    void fetchAccounts();
  }, [fetchAccounts]);

  const handleDelete = async (acc: AccountSummary) => {
    const msg = acc.is_active
      ? `Delete the ACTIVE account "${acc.alias}"?\n\nThis will disconnect the WebSocket and clear local trade history for this account. You'll need to add or activate another account before trading.`
      : `Delete account "${acc.alias}"? Local trade history for this account will be removed.`;
    if (!window.confirm(msg)) return;
    try {
      await deleteAccount(acc.id);
      showToast('success', `Account "${acc.alias}" deleted`);
    } catch (err) {
      showToast('error', (err as Error).message);
    }
  };

  if (loading && accounts.length === 0) {
    return <div className="text-overline text-secondary">Loading accounts...</div>;
  }

  if (accounts.length === 0) {
    return (
      <div className="space-y-3">
        <div className="text-center py-6 px-4 border-2 border-dashed border-divider rounded-lg">
          <p className="text-sm text-primary font-medium mb-1">No accounts yet</p>
          <p className="text-overline text-secondary mb-4">
            Add a Deribit/Tibired account to start trading. Credentials stay
            encrypted on this machine.
          </p>
          <button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors"
          >
            <Plus size={14} /> Add account
          </button>
        </div>
        <AccountFormModal
          open={formOpen}
          account={null}
          endpoints={endpoints}
          onClose={() => setFormOpen(false)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {accounts.map((acc) => (
        <div
          key={acc.id}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-colors ${
            acc.is_active
              ? 'border-accent/40 bg-accent/[0.04]'
              : 'border-divider hover:bg-cream'
          }`}
        >
          {/* Active radio */}
          <button
            onClick={() => {
              if (!acc.is_active) setSwitchTarget(acc);
            }}
            disabled={acc.is_active}
            className={`flex-shrink-0 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
              acc.is_active
                ? 'border-accent bg-accent text-white cursor-default'
                : 'border-divider hover:border-accent'
            }`}
            title={acc.is_active ? 'Active account' : 'Switch to this account'}
          >
            {acc.is_active && <CheckCircle2 size={12} />}
          </button>

          {/* Alias + endpoint */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-primary truncate">
                {acc.alias}
              </span>
              {!acc.is_production && (
                <span className="text-overline text-secondary uppercase tracking-wider font-semibold border border-divider rounded px-1.5 py-0.5">
                  Paper Trade
                </span>
              )}
            </div>
            <div className="text-overline text-secondary font-mono truncate">
              {acc.endpoint_label} · id ••••{acc.client_id_tail}
              {acc.client_secret_tail ? ` · secret ••••${acc.client_secret_tail}` : ''}
            </div>
          </div>

          {/* Edit / Delete */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              onClick={() => {
                setEditing(acc);
                setFormOpen(true);
              }}
              className="p-2 rounded text-secondary hover:text-primary hover:bg-white transition-colors"
              title="Edit alias or rotate secret"
            >
              <Edit2 size={14} />
            </button>
            <button
              onClick={() => handleDelete(acc)}
              className="p-2 rounded text-secondary hover:text-loss hover:bg-loss/5 transition-colors"
              title={acc.is_active ? 'Delete active account (will disconnect)' : 'Delete account'}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      ))}

      {/* Add button */}
      <button
        onClick={() => {
          setEditing(null);
          setFormOpen(true);
        }}
        className="mt-2 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-dashed border-divider text-secondary hover:text-primary hover:border-accent text-xs font-semibold transition-colors"
      >
        <Plus size={14} /> Add account
      </button>

      <AccountFormModal
        open={formOpen}
        account={editing}
        endpoints={endpoints}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
      />

      <SwitchAccountModal
        target={switchTarget}
        currentId={activeId}
        onClose={() => setSwitchTarget(null)}
      />
    </div>
  );
}

export default AccountList;
