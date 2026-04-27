import { useEffect, useState, useCallback } from 'react';
import { ChevronUp, ChevronDown, Pause, Play, Zap, X, Check } from 'lucide-react';
import { useSmartOrdersStore } from '../../stores/smartOrders';
import { cancelSmartOrder, smartOrderAction } from '../../api/client';

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function SmartOrderBar() {
  const { orders, fetchOrders, updateOrder, removeOrder } = useSmartOrdersStore();
  const [expanded, setExpanded] = useState(true);
  const [, setTick] = useState(0);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // Tick every second to update elapsed times
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const activeOrders = orders.filter((o) => o.state === 'active' || o.state === 'triggered');
  const completedOrders = orders.filter((o) => o.state === 'filled' || o.state === 'cancelled');

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
    <div className="fixed bottom-0 left-sidebar right-0 bg-white shadow-card border-t border-divider z-30">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-6 h-10 text-xs font-semibold text-secondary uppercase tracking-wider hover:bg-cream/50 transition-colors"
      >
        <span>Smart Orders ({activeOrders.length} active)</span>
        {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      {expanded && (
        <div className="max-h-48 overflow-y-auto divide-y divide-divider/50">
          {/* Active orders */}
          {activeOrders.map((order) => (
            <div
              key={order.id}
              className="flex items-center gap-4 px-6 py-2 text-sm hover:bg-cream/30 transition-colors"
            >
              <span className="font-medium text-primary w-36 truncate">
                {order.instrument}
              </span>
              <span
                className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                  order.direction === 'buy'
                    ? 'bg-profit-bg text-profit'
                    : 'bg-loss-bg text-loss'
                }`}
              >
                {order.direction.toUpperCase()}
              </span>
              <span className="font-mono text-primary w-24 text-right">
                {order.amount}
              </span>
              <span className="text-secondary text-xs w-20">
                {order.amend_count} amends
              </span>
              <span className="text-secondary text-xs font-mono w-16">
                {formatElapsed(order.elapsed_ms)}
              </span>
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
          ))}

          {/* Completed orders */}
          {completedOrders.slice(0, 5).map((order) => (
            <div
              key={order.id}
              className="flex items-center gap-4 px-6 py-2 text-sm opacity-60"
            >
              <Check size={14} className="text-profit" />
              <span className="font-medium text-primary w-36 truncate">
                {order.instrument}
              </span>
              <span
                className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                  order.direction === 'buy'
                    ? 'bg-profit-bg text-profit'
                    : 'bg-loss-bg text-loss'
                }`}
              >
                {order.direction.toUpperCase()}
              </span>
              <span className="font-mono text-primary w-24 text-right">
                {order.amount}
              </span>
              <span className="text-xs text-profit ml-auto">
                {order.state === 'filled' ? 'Filled' : 'Cancelled'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default SmartOrderBar;
