import { useEffect, useState, useCallback } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import * as Slider from '@radix-ui/react-slider';
import Card from '../components/common/Card';
import Skeleton from '../components/common/Skeleton';
import {
  getSettingsStatus,
  saveCredentials,
  switchEnv,
  clearKeys,
} from '../api/client';
import { useSettingsStore, getReadableIntervals } from '../stores/settings';
import { useToastStore } from '../stores/toast';

interface SettingsStatusData {
  env: string;
  ws_url: string;
  connected: boolean;
  authenticated: boolean;
  client_id: string;
  is_production: boolean;
  allow_live_trading: boolean;
  uptime_ms: number;
  client_id_tail: string;
  has_credentials: boolean;
  production_endpoint: string;
}

function formatUptime(ms: number): string {
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${minutes}m`;
}

function Settings() {
  const [status, setStatus] = useState<SettingsStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { autoRefresh, speed, setAutoRefresh, setSpeed } = useSettingsStore();

  const [activeEnv, setActiveEnv] = useState<string>('testnet');
  const [prodEndpoint, setProdEndpoint] = useState<string>('deribit.com');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);

  const showToast = useToastStore((s) => s.show);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getSettingsStatus();
      setStatus(data);
      setActiveEnv(data.env);
      if (data.production_endpoint) {
        setProdEndpoint(data.production_endpoint);
      }
    } catch {
      showToast('error', 'Failed to fetch settings status');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleEnvSwitch = useCallback(
    async (env: string) => {
      if (env === activeEnv) return;

      if (env === 'production') {
        const confirmed = window.confirm(
          'You are switching to PRODUCTION. Real funds will be at risk. Continue?',
        );
        if (!confirmed) return;
      }

      try {
        await switchEnv(env);
        setActiveEnv(env);
        showToast('success', `Switched to ${env}`);
        await fetchStatus();
      } catch {
        showToast('error', 'Failed to switch environment');
      }
    },
    [activeEnv, fetchStatus, showToast],
  );

  const handleSave = useCallback(async () => {
    if (!clientId.trim() || !clientSecret.trim()) {
      showToast('error', 'Client ID and Secret are required');
      return;
    }

    setSaving(true);
    try {
      await saveCredentials({
        client_id: clientId,
        client_secret: clientSecret,
        env: activeEnv,
        endpoint: prodEndpoint,
      });
      showToast('success', 'Credentials saved, reconnecting...');
      setClientSecret('');
      setClientId('');
      await fetchStatus();
    } catch {
      showToast('error', 'Failed to save credentials');
    } finally {
      setSaving(false);
    }
  }, [clientId, clientSecret, activeEnv, prodEndpoint, fetchStatus, showToast]);

  const handleClearKeys = useCallback(async () => {
    const confirmed = window.confirm(
      `Clear API keys for ${activeEnv}? This cannot be undone.`,
    );
    if (!confirmed) return;

    try {
      await clearKeys(activeEnv);
      showToast('success', 'API keys cleared');
      setClientId('');
      setClientSecret('');
      await fetchStatus();
    } catch {
      showToast('error', 'Failed to clear keys');
    }
  }, [activeEnv, fetchStatus, showToast]);

  const connected = status?.connected ?? false;
  const isHealthy = connected;
  const hasCreds = status?.has_credentials ?? false;
  const tail = status?.client_id_tail ?? '';

  const readableIntervals = getReadableIntervals(speed);

  return (
    <div className="space-y-4">

      {/* Card 1: Account Configuration */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4">
          Account Configuration
        </div>

        {/* Environment Toggle */}
        <div className="mb-4">
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            Environment
          </div>
          <div className="flex gap-1 bg-cream rounded-lg p-1 w-fit">
            {['testnet', 'production'].map((env) => (
              <button
                key={env}
                onClick={() => handleEnvSwitch(env)}
                className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors capitalize ${
                  activeEnv === env
                    ? 'bg-primary text-white'
                    : 'text-secondary hover:text-primary'
                }`}
              >
                {env}
              </button>
            ))}
          </div>
        </div>

        {/* Production Endpoint (only when env=production) */}
        {activeEnv === 'production' && (
          <div className="mb-4">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
              Production Endpoint
            </div>
            <div className="flex gap-1 bg-cream rounded-lg p-1 w-fit">
              {['tibired.com', 'deribit.com'].map((ep) => (
                <button
                  key={ep}
                  onClick={() => setProdEndpoint(ep)}
                  className={`px-4 py-1.5 text-xs font-medium font-mono rounded-md transition-colors ${
                    prodEndpoint === ep
                      ? 'bg-primary text-white'
                      : 'text-secondary hover:text-primary'
                  }`}
                >
                  {ep}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* API Credentials */}
        <div className="mb-4">
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            API Credentials
          </div>
          <div className="space-y-3">
            <div>
              <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
                Client ID
              </label>
              <input
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder={hasCreds ? `\u2022\u2022\u2022\u2022${tail}` : 'Enter client ID'}
                className="w-full py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
              />
            </div>

            <div>
              <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
                Secret
              </label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder={hasCreds ? `\u2022\u2022\u2022\u2022${tail}` : 'Enter client secret'}
                  className="w-full py-2 px-3 pr-10 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((prev) => !prev)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary hover:text-primary transition-colors"
                  aria-label={showSecret ? 'Hide secret' : 'Show secret'}
                >
                  {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
              >
                {saving ? 'Saving...' : 'Save & Reconnect'}
              </button>
              <button
                onClick={handleClearKeys}
                className="px-4 py-2 rounded-lg border border-loss/30 text-loss text-xs font-semibold hover:bg-loss/5 transition-colors"
              >
                Clear Keys
              </button>
            </div>

            <p className="text-overline text-secondary">
              Changing API key will clear account history for this environment
            </p>
          </div>
        </div>

        {/* Connection Status */}
        <div>
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            Connection Status
          </div>
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-24" />
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-overline text-secondary uppercase tracking-wider font-semibold">
                  Status
                </span>
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isHealthy ? 'bg-profit' : 'bg-loss'
                    }`}
                  />
                  <span className="text-xs font-medium font-mono text-primary">
                    {isHealthy ? 'Connected' : 'Disconnected'}
                  </span>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-overline text-secondary uppercase tracking-wider font-semibold">
                  URL
                </span>
                <span className="text-xs font-mono text-primary">
                  {status?.ws_url ?? '--'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-overline text-secondary uppercase tracking-wider font-semibold">
                  Uptime
                </span>
                <span className="text-xs font-mono text-primary">
                  {status ? formatUptime(status.uptime_ms) : '--'}
                </span>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Card 2: Trading Client Configuration */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4">
          Trading Client Configuration
        </div>

        {/* Auto Refresh toggle */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-primary font-medium">Auto Refresh</span>
          <div className="flex gap-1 bg-cream rounded-lg p-1">
            <button
              onClick={() => setAutoRefresh(true)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                autoRefresh ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              On
            </button>
            <button
              onClick={() => setAutoRefresh(false)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                !autoRefresh ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              Off
            </button>
          </div>
        </div>

        {/* Speed slider (only when auto refresh is on) */}
        {autoRefresh && (
          <div>
            <Slider.Root
              value={[speed]}
              onValueChange={([v]) => setSpeed(v)}
              min={0}
              max={1}
              step={0.05}
              className="relative flex items-center select-none touch-none w-full h-5"
            >
              <Slider.Track className="bg-cream-dark relative grow rounded-full h-1">
                <Slider.Range className="absolute bg-accent rounded-full h-full" />
              </Slider.Track>
              <Slider.Thumb className="block w-3.5 h-3.5 bg-white border-2 border-accent rounded-full focus:outline-none" />
            </Slider.Root>
            <div className="flex justify-between mt-0.5 text-overline text-disabled">
              <span>Slow</span>
              <span>Fast</span>
            </div>

            {/* Current refresh intervals */}
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-overline font-mono text-secondary">
              <span>Dashboard {readableIntervals.Dashboard}s</span>
              <span>Options {readableIntervals.Options}s</span>
              <span>OrderBook {readableIntervals.OrderBook}s</span>
              <span>Candles {readableIntervals.Candles}s</span>
              <span>Equity {readableIntervals.Equity}s</span>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

export default Settings;
