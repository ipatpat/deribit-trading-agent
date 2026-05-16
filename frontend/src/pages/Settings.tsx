import { useEffect, useState, useCallback } from 'react';
import { Eye, EyeOff, Sparkles, Check, X as XIcon, RefreshCw } from 'lucide-react';
import * as Slider from '@radix-ui/react-slider';
import Card from '../components/common/Card';
import AccountList from '../components/account/AccountList';
import {
  getAiAgentConfig,
  setAiAgentConfig,
  deleteAiAgentConfig,
  testAiAgentConnection,
  listAiAgentModels,
  type AiAgentConfigPublic,
  type TestConnectionResult,
} from '../api/aiAgent';
import { useSettingsStore, getReadableIntervals } from '../stores/settings';
import { useToastStore } from '../stores/toast';

const DEFAULT_AI_ENDPOINT = 'https://api.deepseek.com';
const DEFAULT_AI_MODEL = 'deepseek-chat';

function AiAgentCard() {
  const [cfg, setCfg] = useState<AiAgentConfigPublic | null>(null);
  const [endpoint, setEndpoint] = useState(DEFAULT_AI_ENDPOINT);
  const [model, setModel] = useState<string>(DEFAULT_AI_MODEL);
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [modelFetchError, setModelFetchError] = useState<string | null>(null);
  const showToast = useToastStore((s) => s.show);

  const refresh = useCallback(async () => {
    try {
      const data = await getAiAgentConfig();
      setCfg(data);
      if (data.endpoint) setEndpoint(data.endpoint);
      if (data.model) setModel(data.model);
    } catch {
      showToast('error', 'Failed to fetch AI agent config');
    }
  }, [showToast]);

  useEffect(() => {
    void refresh();
    if (window.location.hash === '#ai-agent') {
      requestAnimationFrame(() => {
        document.getElementById('ai-agent')?.scrollIntoView({ behavior: 'smooth' });
      });
    }
  }, [refresh]);

  const handleSave = async () => {
    if (!endpoint.trim() || !model.trim() || !apiKey.trim()) {
      showToast('error', 'Endpoint, model, and API key are all required');
      return;
    }
    setSaving(true);
    try {
      await setAiAgentConfig({ endpoint, model, api_key: apiKey });
      showToast('success', 'AI agent configured');
      setApiKey('');
      await refresh();
    } catch (err) {
      showToast('error', `Failed to save: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  // When a key is already saved, the user shouldn't have to retype it to
  // test or list models — the backend falls back to the keystore copy.
  const canUseSavedKey = !!cfg?.api_key_set;

  const handleFetchModels = useCallback(async () => {
    const haveKey = apiKey.trim() || canUseSavedKey;
    if (!endpoint.trim() || !haveKey) {
      setModelFetchError(canUseSavedKey ? 'Endpoint required' : 'Endpoint and API key required');
      return;
    }
    setFetchingModels(true);
    setModelFetchError(null);
    try {
      const result = await listAiAgentModels(endpoint, apiKey);
      if (result.ok && result.models) {
        setAvailableModels(result.models);
        if (result.models.length > 0 && !result.models.includes(model)) {
          setModel(result.models[0]);
        }
      } else {
        setModelFetchError(result.error || 'Failed to fetch models');
      }
    } catch (err) {
      setModelFetchError((err as Error).message);
    } finally {
      setFetchingModels(false);
    }
  }, [endpoint, apiKey, model, canUseSavedKey]);

  const handleTest = async () => {
    const haveKey = apiKey.trim() || canUseSavedKey;
    if (!endpoint.trim() || !model.trim() || !haveKey) {
      setTestResult({
        ok: false,
        error: canUseSavedKey
          ? 'Endpoint and model required'
          : 'All three fields required to test',
      });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      // Pass empty api_key when relying on the saved one — backend will look
      // it up from the keystore.
      const result = await testAiAgentConnection({ endpoint, model, api_key: apiKey });
      setTestResult(result);
      if (result.ok && availableModels.length === 0) {
        void handleFetchModels();
      }
    } catch (err) {
      setTestResult({ ok: false, error: (err as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('Clear AI agent config? This will reset endpoint, model, and API key.')) return;
    try {
      await deleteAiAgentConfig();
      setApiKey('');
      setEndpoint(DEFAULT_AI_ENDPOINT);
      setModel(DEFAULT_AI_MODEL);
      setAvailableModels([]);
      setTestResult(null);
      showToast('success', 'AI agent config cleared');
      await refresh();
    } catch (err) {
      showToast('error', `Failed to clear: ${(err as Error).message}`);
    }
  };

  const envFallback = cfg?.env_fallback_available && !cfg?.api_key_set;

  return (
    <Card>
      <div id="ai-agent" className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4 flex items-center gap-2">
        <Sparkles size={14} className="text-accent" />
        AI Agent
      </div>

      {envFallback && (
        <div className="mb-3 p-2 rounded bg-accent/[0.06] border border-accent/20 text-xs text-primary">
          Using env vars (override here to use Settings).
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
            Endpoint URL
          </label>
          <input
            type="text"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder={DEFAULT_AI_ENDPOINT}
            className="w-full py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
          />
        </div>

        <div>
          <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
            Model
          </label>
          <div className="flex gap-2">
            {availableModels.length > 0 ? (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex-1 py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors bg-white"
              >
                {availableModels.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
                {model && !availableModels.includes(model) && (
                  <option value={model}>{model} (current)</option>
                )}
              </select>
            ) : (
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={DEFAULT_AI_MODEL}
                className="flex-1 py-2 px-3 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
              />
            )}
            <button
              type="button"
              onClick={handleFetchModels}
              disabled={fetchingModels || !endpoint.trim() || !apiKey.trim()}
              className="px-3 py-2 rounded-lg border border-divider text-secondary hover:text-primary hover:bg-cream transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Fetch available models from the endpoint"
            >
              <RefreshCw size={14} className={fetchingModels ? 'animate-spin' : ''} />
            </button>
          </div>
          {modelFetchError && (
            <p className="mt-1 text-overline text-loss">{modelFetchError}</p>
          )}
          {availableModels.length > 0 && (
            <p className="mt-1 text-overline text-secondary">
              {availableModels.length} models available
            </p>
          )}
        </div>

        <div>
          <label className="block text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
            API Key {cfg?.api_key_set && (
              <span className="text-secondary normal-case font-normal">
                (saved · ••••{cfg?.api_key_tail ?? ''} — fill to replace)
              </span>
            )}
          </label>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={cfg?.api_key_set ? `••••${cfg?.api_key_tail ?? ''}` : 'Enter API key'}
              className="w-full py-2 px-3 pr-10 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary hover:text-primary transition-colors"
              aria-label={showKey ? 'Hide key' : 'Show key'}
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <div className="flex gap-2 items-center">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 rounded-lg border border-divider text-primary text-xs font-semibold hover:bg-cream transition-colors disabled:opacity-40"
          >
            {testing ? 'Testing...' : 'Test connection'}
          </button>
          {cfg?.api_key_set && (
            <button
              onClick={handleClear}
              className="px-4 py-2 rounded-lg border border-loss/30 text-loss text-xs font-semibold hover:bg-loss/5 transition-colors"
            >
              Clear
            </button>
          )}
        </div>

        {testResult && (
          <div
            className={`flex items-center gap-2 p-2 rounded text-xs ${
              testResult.ok
                ? 'bg-profit-bg text-profit border border-profit/20'
                : 'bg-loss-bg text-loss border border-loss/20'
            }`}
          >
            {testResult.ok ? <Check size={14} /> : <XIcon size={14} />}
            <span className="font-medium">
              {testResult.ok
                ? `Connected (${testResult.model ?? model})`
                : `${testResult.code ?? 'failed'}: ${testResult.error ?? 'unknown'}`}
            </span>
          </div>
        )}

        <p className="text-overline text-secondary leading-relaxed mt-3">
          Write mode allows Vida to place / cancel orders, gated by a per-call
          confirmation card. Toggle it from the lock icon in the chat header.
        </p>
      </div>
    </Card>
  );
}

function Settings() {
  const { autoRefresh, speed, setAutoRefresh, setSpeed } = useSettingsStore();
  const readableIntervals = getReadableIntervals(speed);

  return (
    <div className="space-y-4">
      {/* Card 1: Accounts */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
          Accounts
        </div>
        <p className="text-overline text-secondary mb-4">
          Manage your Deribit / Tibired trading accounts. Switch the active
          account from here or the top-right chip. Credentials are encrypted
          locally with your master password.
        </p>
        <AccountList />
      </Card>

      {/* Card 2: Trading Client Configuration */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4">
          Trading Client Configuration
        </div>

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

      {/* Card 3: AI Agent Configuration */}
      <AiAgentCard />
    </div>
  );
}

export default Settings;
