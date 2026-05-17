import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { useChatStore } from '../../stores/chat';

interface ConfirmationCardProps {
  toolCallId: string;
  toolName: string;
  toolInput: unknown;
  summary: string;
}

const TIMEOUT_SECONDS = 30;

type CardState = 'pending' | 'submitting' | 'cancelled';

// ── Field formatters ────────────────────────────────────────────────────────
// Each tool's args are turned into a list of label/value rows so the user
// sees a clean order ticket, not a JSON blob or a sentence.

interface Field {
  label: string;
  value: string;
  emphasize?: boolean; // bold + larger value (for side / amount)
}

function _capitalize(s: unknown): string {
  if (typeof s !== 'string') return String(s ?? '');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function _formatFields(toolName: string, args: any): Field[] {
  if (!args || typeof args !== 'object') return [];
  switch (toolName) {
    case 'place_order': {
      const dir = String(args.direction ?? '').toUpperCase();
      const fields: Field[] = [
        { label: 'Instrument', value: String(args.instrument_name ?? '?') },
        { label: 'Side', value: dir, emphasize: true },
        { label: 'Amount', value: String(args.amount ?? '?'), emphasize: true },
        { label: 'Order type', value: String(args.order_type ?? 'limit') },
      ];
      if (args.price !== undefined && args.price !== null) {
        fields.push({ label: 'Price', value: `$${Number(args.price).toLocaleString()}` });
      }
      if (args.label) fields.push({ label: 'Label', value: String(args.label) });
      return fields;
    }
    case 'cancel_order':
      return [{ label: 'Order ID', value: String(args.order_id ?? '?'), emphasize: true }];
    case 'smart_order': {
      const dir = String(args.direction ?? '').toUpperCase();
      const fields: Field[] = [
        { label: 'Instrument', value: String(args.instrument_name ?? '?') },
        { label: 'Side', value: dir, emphasize: true },
        { label: 'Amount', value: String(args.amount ?? '?'), emphasize: true },
        { label: 'Intent', value: _capitalize(args.intent ?? 'standard') },
      ];
      const overrides = (args.overrides ?? {}) as Record<string, unknown>;
      if (typeof overrides.t_patience_ms === 'number') {
        fields.push({ label: 'Patience', value: `${overrides.t_patience_ms} ms` });
      }
      if (typeof overrides.max_cross_levels === 'number') {
        fields.push({ label: 'Max cross levels', value: String(overrides.max_cross_levels) });
      }
      if (typeof overrides.price_limit_pct === 'number') {
        fields.push({
          label: 'Price limit',
          value: `±${(overrides.price_limit_pct * 100).toFixed(2)}%`,
        });
      }
      if (typeof overrides.price_limit_ticks === 'number') {
        fields.push({
          label: 'Price limit',
          value: `±${overrides.price_limit_ticks} ticks`,
        });
      }
      if (typeof overrides.price_limit_iv === 'number') {
        fields.push({
          label: 'Price limit',
          value: `±${(overrides.price_limit_iv * 100).toFixed(1)} vol pts`,
        });
      }
      if (typeof overrides.prefer_maker === 'boolean') {
        fields.push({ label: 'Prefer maker', value: overrides.prefer_maker ? 'Yes' : 'No' });
      }
      return fields;
    }
    case 'cancel_smart_order':
      return [{ label: 'Smart order ID', value: String(args.id ?? '?'), emphasize: true }];
    default: {
      // Fallback for unknown tools — show top-level keys as rows.
      return Object.entries(args).map(([k, v]) => ({
        label: k,
        value: typeof v === 'object' ? JSON.stringify(v) : String(v),
      }));
    }
  }
}

function ConfirmationCard({ toolCallId, toolName, toolInput, summary }: ConfirmationCardProps) {
  const confirmTool = useChatStore((s) => s.confirmTool);
  const [state, setState] = useState<CardState>('pending');
  const [showRawJson, setShowRawJson] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(TIMEOUT_SECONDS);
  const resolvedRef = useRef(false);

  // Tick down countdown; auto-cancel at 0.
  useEffect(() => {
    if (state !== 'pending') return;
    const timer = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(timer);
          if (!resolvedRef.current) {
            resolvedRef.current = true;
            setState('cancelled');
            void confirmTool(toolCallId, false, 'ui_timeout');
          }
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [state, toolCallId, confirmTool]);

  const handleConfirm = () => {
    if (resolvedRef.current) return;
    resolvedRef.current = true;
    setState('submitting');
    void confirmTool(toolCallId, true);
  };

  const handleCancel = () => {
    if (resolvedRef.current) return;
    resolvedRef.current = true;
    setState('cancelled');
    void confirmTool(toolCallId, false);
  };

  const fields = _formatFields(toolName, toolInput);
  const argsJson = JSON.stringify(toolInput ?? {}, null, 2);
  const pct = (secondsLeft / TIMEOUT_SECONDS) * 100;
  const lowTime = secondsLeft <= 10;
  const disabled = state !== 'pending';

  return (
    <div className="my-2 border-2 border-loss/40 rounded-lg bg-white overflow-hidden shadow-sm">
      <div className="flex items-center gap-2 px-3 py-2 bg-loss-bg border-b border-loss/30">
        <AlertTriangle size={14} className="text-loss flex-shrink-0" />
        <span className="text-xs font-bold text-loss flex-1 font-mono">
          {toolName}
        </span>
        <span
          className={`text-xs font-mono font-bold tabular-nums ${
            lowTime ? 'text-loss animate-pulse' : 'text-secondary'
          }`}
        >
          {secondsLeft}s
        </span>
      </div>

      <div className="px-3 py-2.5">
        {/* Field/value table — the structured "order ticket" */}
        <dl className="space-y-1.5 mb-2">
          {fields.map((f) => (
            <div key={f.label} className="flex items-baseline justify-between gap-3">
              <dt className="text-[10px] text-secondary uppercase tracking-wider font-semibold flex-shrink-0">
                {f.label}
              </dt>
              <dd
                className={`font-mono text-right break-all ${
                  f.emphasize
                    ? 'text-sm font-bold text-primary'
                    : 'text-xs text-primary'
                }`}
              >
                {f.value}
              </dd>
            </div>
          ))}
        </dl>

        {/* Backend-generated summary as one-line subtitle (often includes
            derived fields like notional / fee that aren't in raw args). */}
        {summary && (
          <p className="text-[11px] text-secondary italic border-t border-divider/40 pt-2 mt-2">
            {summary}
          </p>
        )}

        <button
          type="button"
          onClick={() => setShowRawJson((v) => !v)}
          className="mt-2 flex items-center gap-1 text-[10px] text-secondary hover:text-primary"
        >
          {showRawJson ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          {showRawJson ? 'Hide raw JSON' : 'Show raw JSON'}
        </button>
        {showRawJson && (
          <pre className="mt-1 p-2 rounded bg-cream-light border border-divider/60 font-mono text-[10px] text-primary overflow-x-auto max-h-40">
            {argsJson}
          </pre>
        )}
      </div>

      <div className="px-3 pb-3 flex gap-2 justify-end">
        <button
          type="button"
          onClick={handleCancel}
          disabled={disabled}
          className="px-4 py-1.5 rounded-lg text-xs font-semibold text-secondary hover:text-primary hover:bg-cream transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {state === 'cancelled' ? 'Cancelled' : 'Cancel'}
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={disabled}
          className="px-4 py-1.5 rounded-lg bg-loss text-white text-xs font-bold hover:bg-loss/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {state === 'submitting' ? 'Submitting…' : 'Confirm trade'}
        </button>
      </div>

      <div className="h-1 bg-cream-dark relative overflow-hidden">
        <div
          className={`h-full transition-all duration-1000 ease-linear ${
            lowTime ? 'bg-loss' : 'bg-accent'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default ConfirmationCard;
