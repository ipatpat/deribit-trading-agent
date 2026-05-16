import { useState } from 'react';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import { type AccountSummary } from '../../api/accounts';
import { useAccountsStore } from '../../stores/accounts';
import { useSmartOrdersStore } from '../../stores/smartOrders';
import { useChatStore } from '../../stores/chat';
import { useToastStore } from '../../stores/toast';

interface Props {
  target: AccountSummary | null;
  currentId: string | null;
  onClose: () => void;
}

function SwitchAccountModal({ target, currentId, onClose }: Props) {
  const activate = useAccountsStore((s) => s.activate);
  const accounts = useAccountsStore((s) => s.accounts);
  const showToast = useToastStore((s) => s.show);
  const orders = useSmartOrdersStore((s) => s.orders);
  const messages = useChatStore((s) => s.messages);
  const writeEnabled = useChatStore((s) => s.writeEnabled);

  const [switching, setSwitching] = useState(false);

  if (!target) return null;

  const current = currentId ? accounts.find((a) => a.id === currentId) : null;
  // SmartOrder.state values like "filled"/"cancelled"/"error" are terminal;
  // everything else counts as in-flight for the warning.
  const activeSmartOrders = orders.filter(
    (o) => !['filled', 'cancelled', 'error'].includes(o.state),
  ).length;

  const hasChat = messages.length > 0;

  const handleConfirm = async () => {
    setSwitching(true);
    try {
      await activate(target.id);
      showToast('success', `Switched to "${target.alias}"`);
      onClose();
    } catch (err) {
      showToast('error', `Switch failed: ${(err as Error).message}`);
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-card shadow-card w-full max-w-md p-5">
        <div className="text-lg font-semibold text-primary mb-4">
          Switch account
        </div>

        {/* From → To */}
        <div className="flex items-center gap-3 px-3 py-3 bg-cream rounded-lg mb-4">
          <div className="flex-1 min-w-0">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-0.5">
              From
            </div>
            <div className="text-sm text-primary truncate">
              {current?.alias ?? '(none)'}
            </div>
            {current && (
              <div className="text-overline text-secondary font-mono truncate">
                {current.endpoint_label}
              </div>
            )}
          </div>
          <ArrowRight size={16} className="text-secondary flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-0.5">
              To
            </div>
            <div className="text-sm text-primary font-semibold truncate">
              {target.alias}
            </div>
            <div className="text-overline text-secondary font-mono truncate">
              {target.endpoint_label}
            </div>
          </div>
        </div>

        {/* Production warning */}
        {target.is_production && (
          <div className="mb-3 px-3 py-2 rounded-lg border border-loss/30 bg-loss-bg text-loss text-xs">
            <div className="flex items-start gap-2">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold mb-0.5">Production account</div>
                <div className="text-loss/80">
                  Trades placed will move real funds.
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Conditional warnings */}
        {(activeSmartOrders > 0 || writeEnabled || hasChat) && (
          <div className="mb-3 px-3 py-2 rounded-lg border border-divider bg-cream text-xs space-y-1.5">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold">
              What happens on switch
            </div>
            {activeSmartOrders > 0 && (
              <div className="text-primary">
                · <span className="font-semibold">{activeSmartOrders}</span>{' '}
                in-flight smart order
                {activeSmartOrders === 1 ? '' : 's'} on the current account.
                Local tracking will be dropped; the orders stay on Deribit.
              </div>
            )}
            {writeEnabled && (
              <div className="text-primary">
                · AI trading will switch back to <span className="font-semibold">Read only</span>{' '}
                — you'll re-arm it on the new account.
              </div>
            )}
            {hasChat && (
              <div className="text-primary">
                · Chat history is per-account. The current conversation stays
                with the current account.
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={switching}
            className="px-4 py-2 rounded-lg border border-divider text-secondary text-xs font-semibold hover:bg-cream transition-colors disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={switching}
            className="px-4 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
          >
            {switching ? 'Switching...' : `Switch to "${target.alias}"`}
          </button>
        </div>
      </div>
    </div>
  );
}

export default SwitchAccountModal;
