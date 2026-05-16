import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, Plus, Settings as SettingsIcon, CheckCircle2 } from 'lucide-react';
import { useAccountsStore, selectActiveAccount } from '../../stores/accounts';
import { type AccountSummary } from '../../api/accounts';
import SwitchAccountModal from '../account/SwitchAccountModal';

function AccountChip() {
  const accounts = useAccountsStore((s) => s.accounts);
  const activeId = useAccountsStore((s) => s.activeId);
  const fetchAccounts = useAccountsStore((s) => s.fetchAccounts);
  const fetchActive = useAccountsStore((s) => s.fetchActive);
  const active = useAccountsStore(selectActiveAccount);

  const [open, setOpen] = useState(false);
  const [switchTarget, setSwitchTarget] = useState<AccountSummary | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void fetchAccounts();
    // Cheap initial probe of connection state.
    void fetchActive();
  }, [fetchAccounts, fetchActive]);

  // Close dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  // No active account — show an orange "Add account" CTA pointing at /settings.
  if (!active) {
    return (
      <Link
        to="/settings"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-loss/40 bg-loss-bg text-loss text-xs font-semibold hover:bg-loss/10 transition-colors"
        title="No account configured — click to add one"
      >
        <Plus size={12} /> Add account
      </Link>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-divider text-primary text-xs font-semibold hover:bg-cream transition-colors"
        title={`${active.alias} · ${active.endpoint_label}`}
      >
        <span className="truncate max-w-[120px]">{active.alias}</span>
        {!active.is_production && (
          <span className="text-overline text-secondary uppercase tracking-wider font-semibold border border-divider rounded px-1 py-0">
            Paper
          </span>
        )}
        <ChevronDown size={12} className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-64 bg-white border border-divider rounded-card shadow-card z-50 overflow-hidden">
          {/* Active section */}
          <div className="px-3 py-2 bg-cream border-b border-divider">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-0.5">
              Active
            </div>
            <div className="flex items-center gap-1.5">
              <CheckCircle2 size={12} className="text-accent" />
              <span className="text-sm text-primary font-semibold truncate">{active.alias}</span>
              {!active.is_production && (
                <span className="text-overline text-secondary uppercase tracking-wider font-semibold ml-auto border border-divider rounded px-1.5 py-0.5">
                  Paper Trade
                </span>
              )}
            </div>
            <div className="text-overline text-secondary font-mono truncate mt-0.5">
              {active.endpoint_label} · ••••{active.client_id_tail}
            </div>
          </div>

          {/* Other accounts */}
          {accounts.filter((a) => a.id !== activeId).length > 0 && (
            <div className="py-1">
              <div className="px-3 py-1 text-overline text-secondary uppercase tracking-wider font-semibold">
                Switch to
              </div>
              {accounts
                .filter((a) => a.id !== activeId)
                .map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      setSwitchTarget(a);
                      setOpen(false);
                    }}
                    className="w-full px-3 py-1.5 flex items-center gap-2 hover:bg-cream text-left transition-colors"
                  >
                    <span className="text-sm text-primary truncate flex-1">{a.alias}</span>
                    {!a.is_production && (
                      <span className="text-overline text-secondary uppercase tracking-wider font-semibold border border-divider rounded px-1.5 py-0.5">
                        Paper Trade
                      </span>
                    )}
                  </button>
                ))}
            </div>
          )}

          {/* Actions */}
          <div className="border-t border-divider py-1">
            <Link
              to="/settings"
              onClick={() => setOpen(false)}
              className="px-3 py-1.5 flex items-center gap-2 text-xs text-secondary hover:text-primary hover:bg-cream transition-colors"
            >
              <SettingsIcon size={12} /> Manage accounts
            </Link>
          </div>
        </div>
      )}

      <SwitchAccountModal
        target={switchTarget}
        currentId={activeId}
        onClose={() => setSwitchTarget(null)}
      />
    </div>
  );
}

export default AccountChip;
