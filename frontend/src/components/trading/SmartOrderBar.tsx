import { useEffect, useState, useCallback } from 'react';
import { ChevronUp, ChevronDown, Pause, Zap, X, Check, Loader2 } from 'lucide-react';
import { useSmartOrdersStore } from '../../stores/smartOrders';
import { usePortfolioStore } from '../../stores/portfolio';
import { useChatStore } from '../../stores/chat';
import { cancelSmartOrder, smartOrderAction } from '../../api/client';
import type { SmartOrderState } from '../../types/api';
import { feeSavedUsd, IntentBadge, LevelBadge } from '../../utils/smartOrderFormat';

const ACTIVE_STATES: ReadonlySet<SmartOrderState> = new Set([
  'pending',
  'active',
  'escalating',
  'paused',
]);

const TERMINAL_STATES: ReadonlySet<SmartOrderState> = new Set([
  'completed',
  'cancelled',
  'market_filled',
  'failed',
]);

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function ProgressBar({ elapsed, budget }: { elapsed: number; budget: number | null }) {
  if (!budget || budget <= 0) return null;
  const pct = Math.min(100, (elapsed / budget) * 100);
  const overBudget = elapsed > budget;
  return (
    <div className="flex items-center gap-2 w-32">
      <div className="flex-1 h-1.5 rounded-full bg-cream-dark overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${overBudget ? 'bg-loss' : 'bg-secondary'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-secondary font-mono whitespace-nowrap">
        {formatElapsed(elapsed)}/{formatElapsed(budget)}
      </span>
    </div>
  );
}

function SmartOrderBar() {
  const { orders, fetchOrders, updateOrder, removeOrder } = useSmartOrdersStore();
  const indexPrices = usePortfolioStore((s) => s.indexPrices);
  const fetchIndexPrices = usePortfolioStore((s) => s.fetchIndexPrices);
  const chatOpen = useChatStore((s) => s.open);
  const [expanded, setExpanded] = useState(true);
  const [, setTick] = useState(0);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  useEffect(() => {
    fetchIndexPrices();
    const id = setInterval(() => fetchIndexPrices(), 30_000);
    return () => clearInterval(id);
  }, [fetchIndexPrices]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const activeOrders = orders.filter((o) => ACTIVE_STATES.has(o.state));
  const completedOrders = orders.filter((o) => TERMINAL_STATES.has(o.state));

  const handleAction = useCallback(
    async (id: string, action: string) => {
      try {
        if (action === 'cancel') {
          await cancelSmartOrder(id);
          removeOrder(id);
        } else {
          const updated = await smartOrderAction(id, action);
          updateOrder(updated);
        }
      } catch {
        // silently handle
      }
    },
    [removeOrder, updateOrder],
  );

  if (orders.length === 0) return null;

  return (
    <div className={`fixed bottom-0 left-sidebar bg-white shadow-card border-t border-divider z-30 transition-[right] duration-200 ${chatOpen ? 'right-chat-sidebar' : 'right-0'}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-6 h-10 text-xs font-semibold text-secondary uppercase tracking-wider hover:bg-cream/50 transition-colors"
      >
        <span>Smart Orders ({activeOrders.length} active)</span>
        {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      {expanded && (
        <div className="max-h-48 overflow-y-auto divide-y divide-divider/50">
          {activeOrders.map((order) => {
            const isEscalating = order.state === 'escalating';
            const nextLevel = Math.min(4, order.current_level + 1);
            return (
              <div
                key={order.id}
                className="flex items-center gap-3 px-6 py-2 text-sm hover:bg-cream/30 transition-colors"
              >
                <span className="font-medium text-primary w-32 truncate">{order.instrument}</span>
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                    order.direction === 'buy' ? 'bg-profit-bg text-profit' : 'bg-loss-bg text-loss'
                  }`}
                >
                  {order.direction.toUpperCase()}
                </span>
                <span className="font-mono text-primary w-20 text-right">{order.amount}</span>
                <IntentBadge intent={order.intent} />
                {isEscalating ? (
                  <span className="flex items-center gap-1.5 text-xs text-orange-700 font-medium">
                    <Loader2 size={12} className="animate-spin" />
                    Lv{order.current_level}→Lv{nextLevel} escalating…
                  </span>
                ) : (
                  <>
                    <LevelBadge level={order.current_level} />
                    <ProgressBar elapsed={order.elapsed_ms} budget={order.t_patience_ms} />
                    {order.post_only_reject_count > 0 && (
                      <span
                        className="text-[10px] text-orange-700 font-mono"
                        title="post_only rejects"
                      >
                        ⚠{order.post_only_reject_count}
                      </span>
                    )}
                    <span className="text-secondary text-xs w-16">
                      {order.amend_count} amends
                    </span>
                  </>
                )}
                <div className="ml-auto flex gap-1.5">
                  <button
                    onClick={() => handleAction(order.id, 'pause')}
                    title="Pause"
                    className="p-1.5 rounded hover:bg-cream text-secondary hover:text-primary transition-colors"
                  >
                    <Pause size={14} />
                  </button>
                  <button
                    onClick={() => handleAction(order.id, 'market')}
                    title="Fill at market"
                    className="p-1.5 rounded hover:bg-cream text-secondary hover:text-accent transition-colors"
                  >
                    <Zap size={14} />
                  </button>
                  <button
                    onClick={() => handleAction(order.id, 'cancel')}
                    title="Cancel"
                    className="p-1.5 rounded hover:bg-loss-bg text-secondary hover:text-loss transition-colors"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            );
          })}

          {completedOrders.slice(0, 5).map((order) => {
            const filled = order.state === 'completed' || order.state === 'market_filled';
            const saved = feeSavedUsd(order, indexPrices);
            return (
              <div
                key={order.id}
                className="flex items-center gap-3 px-6 py-2 text-sm opacity-70"
              >
                <Check size={14} className={filled ? 'text-profit' : 'text-secondary'} />
                <span className="font-medium text-primary w-32 truncate">{order.instrument}</span>
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                    order.direction === 'buy' ? 'bg-profit-bg text-profit' : 'bg-loss-bg text-loss'
                  }`}
                >
                  {order.direction.toUpperCase()}
                </span>
                <span className="font-mono text-primary w-20 text-right">{order.amount}</span>
                <IntentBadge intent={order.intent} />
                {filled && <LevelBadge level={order.current_level} />}
                <span className="text-xs text-secondary font-mono">
                  {formatElapsed(order.elapsed_ms)}
                </span>
                {filled && saved !== null && saved >= 0.01 && (
                  <span className="text-[11px] text-profit" title="vs taker">
                    saved ${saved.toFixed(2)}
                  </span>
                )}
                <span
                  className={`text-xs ml-auto ${
                    order.state === 'completed' || order.state === 'market_filled'
                      ? 'text-profit'
                      : order.state === 'failed'
                        ? 'text-loss'
                        : 'text-secondary'
                  }`}
                >
                  {order.state === 'completed'
                    ? 'Filled'
                    : order.state === 'market_filled'
                      ? 'Market'
                      : order.state === 'cancelled'
                        ? 'Cancelled'
                        : 'Failed'}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default SmartOrderBar;
