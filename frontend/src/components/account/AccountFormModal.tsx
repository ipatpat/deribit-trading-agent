import { useEffect, useState } from 'react';
import { Eye, EyeOff, Check, X as XIcon } from 'lucide-react';
import {
  type AccountSummary,
  type EndpointInfo,
  type EndpointId,
  testCredentials,
  testExistingAccount,
} from '../../api/accounts';
import { useAccountsStore } from '../../stores/accounts';
import { useToastStore } from '../../stores/toast';

interface Props {
  open: boolean;
  /** When set, the modal is in edit mode; only alias + secret are mutable. */
  account?: AccountSummary | null;
  endpoints: EndpointInfo[];
  onClose: () => void;
  onSaved?: (id: string) => void;
}

type TestResult =
  | { ok: true; ws_url?: string }
  | { ok: false; stage?: string; error?: string };

function AccountFormModal({ open, account, endpoints, onClose, onSaved }: Props) {
  const editing = !!account;
  const showToast = useToastStore((s) => s.show);
  const addAccount = useAccountsStore((s) => s.addAccount);
  const updateAccount = useAccountsStore((s) => s.updateAccount);

  const [alias, setAlias] = useState('');
  const [endpoint, setEndpoint] = useState<EndpointId>('deribit_testnet');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // Re-seed form when the modal opens or the target account changes.
  useEffect(() => {
    if (!open) return;
    if (account) {
      setAlias(account.alias);
      setEndpoint(account.endpoint);
      setClientId(''); // immutable & sensitive — never show
      setClientSecret('');
    } else {
      setAlias('');
      setEndpoint((endpoints[0]?.id as EndpointId) ?? 'deribit_testnet');
      setClientId('');
      setClientSecret('');
    }
    setTestResult(null);
    setShowSecret(false);
  }, [open, account, endpoints]);

  if (!open) return null;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      let result: TestResult;
      if (editing && account && !clientSecret.trim()) {
        // Editing without a new secret → test the saved credentials.
        result = (await testExistingAccount(account.id)) as TestResult;
      } else {
        if (!clientId.trim() || !clientSecret.trim()) {
          setTestResult({ ok: false, error: 'client_id and secret are required' });
          return;
        }
        result = (await testCredentials({
          endpoint,
          client_id: clientId,
          client_secret: clientSecret,
        })) as TestResult;
      }
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, error: (err as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!alias.trim()) {
      showToast('error', 'Alias is required');
      return;
    }
    setSaving(true);
    try {
      if (editing && account) {
        await updateAccount(account.id, {
          alias: alias.trim() !== account.alias ? alias.trim() : undefined,
          client_secret: clientSecret.trim() || undefined,
        });
        showToast('success', `Account "${alias}" updated`);
        onSaved?.(account.id);
      } else {
        if (!clientId.trim() || !clientSecret.trim()) {
          showToast('error', 'client_id and client_secret are required');
          setSaving(false);
          return;
        }
        const newId = await addAccount({
          alias: alias.trim(),
          endpoint,
          client_id: clientId.trim(),
          client_secret: clientSecret,
        });
        showToast('success', `Account "${alias}" created`);
        onSaved?.(newId);
      }
      onClose();
    } catch (err) {
      showToast('error', (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-card shadow-card w-full max-w-md p-5">
        <div className="text-lg font-semibold text-primary mb-4">
          {editing ? `Edit "${account!.alias}"` : 'Add account'}
        </div>

        <div className="space-y-3">
          {/* Alias */}
          <div>
            <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
              Alias
            </label>
            <input
              type="text"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              placeholder="e.g. main, hedge-fund-1"
              className="w-full py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
            />
          </div>

          {/* Endpoint */}
          <div>
            <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
              Endpoint
            </label>
            <div className="space-y-1.5">
              {endpoints.map((ep) => (
                <label
                  key={ep.id}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer text-sm transition-colors ${
                    endpoint === ep.id
                      ? 'border-accent bg-accent/[0.06]'
                      : 'border-divider hover:bg-cream'
                  } ${editing ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <input
                    type="radio"
                    name="endpoint"
                    value={ep.id}
                    checked={endpoint === ep.id}
                    onChange={() => setEndpoint(ep.id)}
                    disabled={editing}
                    className="accent-accent"
                  />
                  <span className="text-primary font-mono">{ep.label}</span>
                  {!ep.is_production && (
                    <span className="ml-auto text-overline text-secondary uppercase tracking-wider font-semibold border border-divider rounded px-1.5 py-0.5">
                      Paper Trade
                    </span>
                  )}
                </label>
              ))}
            </div>
            {editing && (
              <p className="mt-1 text-overline text-secondary">
                Endpoint is locked. Create a new account to use a different one.
              </p>
            )}
          </div>

          {/* Client ID */}
          <div>
            <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
              Client ID
            </label>
            <input
              type="text"
              value={editing ? `••••${account?.client_id_tail ?? ''}` : clientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={editing}
              placeholder="Enter client ID"
              className="w-full py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors disabled:bg-cream disabled:cursor-not-allowed"
            />
            {editing && (
              <p className="mt-1 text-overline text-secondary">
                Client ID is locked. Create a new account to change it.
              </p>
            )}
          </div>

          {/* Secret */}
          <div>
            <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
              Client Secret {editing && (
                <span className="normal-case font-normal">
                  (saved{account?.client_secret_tail ? ` · ••••${account.client_secret_tail}` : ''} — leave blank to keep)
                </span>
              )}
            </label>
            <div className="relative">
              <input
                type={showSecret ? 'text' : 'password'}
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder={editing ? `••••${account?.client_secret_tail ?? ''}` : 'Enter client secret'}
                className="w-full py-2 px-3 pr-10 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowSecret((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary hover:text-primary"
                aria-label={showSecret ? 'Hide secret' : 'Show secret'}
              >
                {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Test connection */}
          <div className="flex gap-2 items-center">
            <button
              onClick={handleTest}
              disabled={testing}
              className="px-4 py-2 rounded-lg border border-divider text-primary text-xs font-semibold hover:bg-cream transition-colors disabled:opacity-40"
            >
              {testing ? 'Testing...' : 'Test connection'}
            </button>
            {testResult && (
              <div
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                  testResult.ok
                    ? 'bg-profit-bg text-profit border border-profit/20'
                    : 'bg-loss-bg text-loss border border-loss/20'
                }`}
              >
                {testResult.ok ? <Check size={12} /> : <XIcon size={12} />}
                <span className="font-medium">
                  {testResult.ok ? 'OK' : `${testResult.stage ?? 'failed'}: ${testResult.error ?? ''}`}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="mt-5 flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 rounded-lg border border-divider text-secondary text-xs font-semibold hover:bg-cream transition-colors disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
          >
            {saving ? 'Saving...' : editing ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default AccountFormModal;
