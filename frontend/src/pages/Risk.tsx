import { useEffect, useState, useCallback } from 'react';
import { AlertTriangle } from 'lucide-react';
import Card from '../components/common/Card';
import Skeleton from '../components/common/Skeleton';
import PnlText from '../components/common/PnlText';
import { getRiskStatus } from '../api/client';
import { useToastStore } from '../stores/toast';

interface RiskStatus {
  daily_pnl: number;
  trading_paused: boolean;
  last_reset_date?: string;
  config: RiskConfig;
}

interface RiskConfig {
  max_order_size_usd: number;
  max_position_size: number;
  daily_loss_limit_usd: number;
  max_total_delta: number;
  margin_alert_threshold: number;
}

const DEFAULT_CONFIG: RiskConfig = {
  daily_loss_limit_usd: 5000,
  max_order_size_usd: 10,
  max_position_size: 50,
  max_total_delta: 100,
  margin_alert_threshold: 0.8,
};

function Risk() {
  const [status, setStatus] = useState<RiskStatus | null>(null);
  const [config, setConfig] = useState<RiskConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const showToast = useToastStore((s) => s.show);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = (await getRiskStatus()) as unknown as RiskStatus;
      setStatus(data);
      if (data.config) {
        setConfig(data.config);
      }
    } catch {
      showToast('error', 'Failed to fetch risk status');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleSaveConfig = useCallback(async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch('/api/risk/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error('Failed to save');
      showToast('success', 'Risk configuration saved');
      setSaveMsg('Configuration saved');
      setTimeout(() => setSaveMsg(null), 3000);
    } catch {
      showToast('error', 'Failed to save configuration');
      setSaveMsg('Failed to save configuration');
    } finally {
      setSaving(false);
    }
  }, [config, showToast]);

  const handleResume = useCallback(async () => {
    setResuming(true);
    try {
      const res = await fetch('/api/risk/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) throw new Error('Failed to resume');
      showToast('success', 'Trading resumed');
      await fetchStatus();
    } catch {
      showToast('error', 'Failed to resume trading');
    } finally {
      setResuming(false);
    }
  }, [fetchStatus, showToast]);

  const updateConfig = (key: keyof RiskConfig, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: parseFloat(value) || 0 }));
  };

  const dailyPnl = status?.daily_pnl ?? 0;
  const tradingActive = status ? !status.trading_paused : true;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-primary">Risk Management</h1>

      {/* Pause alert banner */}
      {!tradingActive && (
        <div className="flex items-center gap-3 bg-loss-bg border border-loss/20 rounded-card px-5 py-4">
          <AlertTriangle size={20} className="text-loss flex-shrink-0" />
          <div>
            <div className="text-sm font-semibold text-loss">Trading Paused</div>
            <div className="text-sm text-loss/80 mt-0.5">Automated trading has been paused.</div>
          </div>
        </div>
      )}

      {/* Status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Daily PnL */}
        <Card>
          <div className="text-xs text-secondary font-medium uppercase tracking-wider">
            Daily P&L
          </div>
          {loading ? (
            <Skeleton className="h-8 w-28 mt-2" />
          ) : (
            <div className="mt-1 text-2xl font-semibold font-mono">
              <PnlText value={dailyPnl} />
            </div>
          )}
        </Card>

        {/* Trading Status */}
        <Card>
          <div className="text-xs text-secondary font-medium uppercase tracking-wider">
            Trading Status
          </div>
          {loading ? (
            <Skeleton className="h-8 w-24 mt-2" />
          ) : (
            <div className="mt-1 flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  tradingActive ? 'bg-profit' : 'bg-loss'
                }`}
              />
              <span className="text-lg font-semibold text-primary">
                {tradingActive ? 'Active' : 'Paused'}
              </span>
            </div>
          )}
        </Card>

        {/* Last Reset Date */}
        <Card>
          <div className="text-xs text-secondary font-medium uppercase tracking-wider">
            Last Reset Date
          </div>
          {loading ? (
            <Skeleton className="h-8 w-24 mt-2" />
          ) : (
            <div className="mt-1 text-lg font-semibold text-primary">
              {status?.last_reset_date ?? '--'}
            </div>
          )}
        </Card>
      </div>

      {/* Config form */}
      <Card>
        <h3 className="text-sm font-semibold text-primary mb-4">Risk Configuration</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <ConfigField
            label="Daily Loss Limit"
            value={config.daily_loss_limit_usd}
            onChange={(v) => updateConfig('daily_loss_limit_usd', v)}
            prefix="$"
          />
          <ConfigField
            label="Max Order Size"
            value={config.max_order_size_usd}
            onChange={(v) => updateConfig('max_order_size_usd', v)}
            prefix="$"
          />
          <ConfigField
            label="Max Position Size"
            value={config.max_position_size}
            onChange={(v) => updateConfig('max_position_size', v)}
          />
          <ConfigField
            label="Max Total Delta"
            value={config.max_total_delta}
            onChange={(v) => updateConfig('max_total_delta', v)}
          />
          <ConfigField
            label="Margin Alert Threshold"
            value={config.margin_alert_threshold}
            onChange={(v) => updateConfig('margin_alert_threshold', v)}
            suffix="%"
            step="0.01"
          />
        </div>

        <div className="flex items-center gap-3 mt-6">
          <button
            onClick={handleSaveConfig}
            disabled={saving}
            className="px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
          >
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
          {saveMsg && (
            <span
              className={`text-sm ${
                saveMsg.includes('Failed') ? 'text-loss' : 'text-profit'
              }`}
            >
              {saveMsg}
            </span>
          )}
        </div>
      </Card>

      {/* Resume button */}
      {!tradingActive && (
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-primary">Resume Trading</h3>
              <p className="text-sm text-secondary mt-1">
                Re-enable automated trading after reviewing risk parameters.
              </p>
            </div>
            <button
              onClick={handleResume}
              disabled={resuming}
              className="px-6 py-2.5 rounded-lg bg-accent text-white text-sm font-semibold hover:bg-accent/90 transition-colors disabled:opacity-40"
            >
              {resuming ? 'Resuming...' : 'Resume Trading'}
            </button>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Config field helper ── */

function ConfigField({
  label,
  value,
  onChange,
  prefix,
  suffix,
  step = '1',
}: {
  label: string;
  value: number;
  onChange: (value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-secondary font-medium uppercase tracking-wider mb-1.5">
        {label}
      </label>
      <div className="relative">
        {prefix && (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-secondary text-sm">
            {prefix}
          </span>
        )}
        <input
          type="number"
          value={value}
          step={step}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full py-2 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors ${
            prefix ? 'pl-7 pr-3' : 'px-3'
          } ${suffix ? 'pr-7' : ''}`}
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-sm">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

export default Risk;
