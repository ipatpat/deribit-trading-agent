import { useEffect, useState, useCallback } from 'react';
import { Pause, Play, Zap, X } from 'lucide-react';
import Card from '../components/common/Card';
import { useSmartOrdersStore } from '../stores/smartOrders';
import { cancelSmartOrder, smartOrderAction } from '../api/client';
import { useToastStore } from '../stores/toast';

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

const STATUS_BADGE: Record<string, string> = {
  active: 'bg-profit-bg text-profit',
  triggered: 'bg-yellow-100 text-yellow-800',
  filled: 'bg-blue-100 text-blue-800',
  cancelled: 'bg-cream-dark text-secondary',
  error: 'bg-loss-bg text-loss',
};

function SmartOrders() {
  const { orders, loading, fetchOrders, updateOrder, removeOrder } = useSmartOrdersStore();
  const [, setTick] = useState(0);

  const showToast = useToastStore((s) => s.show);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // Tick every second to update elapsed times
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const handleAction = useCallback(
    async (id: string, action: string) => {
      try {
        if (action === 'cancel') {
          await cancelSmartOrder(id);
          removeOrder(id);
          showToast('success', 'Smart order cancelled');
        } else {
          const updated = await smartOrderAction(id, action);
          updateOrder(updated);
          showToast('success', `Smart order ${action}d`);
        }
      } catch {
        showToast('error', `Failed to ${action} smart order`);
      }
    },
    [removeOrder, updateOrder, showToast],
  );

  const activeOrders = orders.filter(
    (o) => o.state === 'active' || o.state === 'triggered',
  );
  const historyOrders = orders.filter(
    (o) => o.state === 'filled' || o.state === 'cancelled' || o.state === 'error',
  );

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-primary">Smart Orders</h1>

      {/* Active Orders */}
      <Card>
        <h3 className="text-sm font-semibold text-primary mb-4">Active Orders</h3>
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-10 bg-cream rounded animate-pulse" />
            ))}
          </div>
        ) : activeOrders.length === 0 ? (
          <div className="text-sm text-secondary py-8 text-center">
            No active smart orders
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white z-10">
                <tr className="border-b border-divider text-overline text-secondary uppercase tracking-wider">
                  <th className="text-left pb-2 pr-3">ID</th>
                  <th className="text-left pb-2 pr-3">Instrument</th>
                  <th className="text-left pb-2 pr-3">Direction</th>
                  <th className="text-right pb-2 pr-3">Amount</th>
                  <th className="text-left pb-2 pr-3">Algorithm</th>
                  <th className="text-left pb-2 pr-3">State</th>
                  <th className="text-right pb-2 pr-3">Amends</th>
                  <th className="text-right pb-2 pr-3">Elapsed</th>
                  <th className="text-right pb-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {activeOrders.map((order) => (
                  <tr
                    key={order.id}
                    className="border-b border-divider/50 hover:bg-cream/50 transition-colors"
                  >
                    <td className="py-2.5 pr-3 font-mono text-xs text-secondary">
                      {order.id.slice(0, 8)}
                    </td>
                    <td className="py-2.5 pr-3 font-medium text-primary">
                      {order.instrument}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          order.direction === 'buy'
                            ? 'bg-profit-bg text-profit'
                            : 'bg-loss-bg text-loss'
                        }`}
                      >
                        {order.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono">{order.amount}</td>
                    <td className="py-2.5 pr-3 text-secondary">{order.algorithm}</td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          STATUS_BADGE[order.state] ?? 'bg-cream text-secondary'
                        }`}
                      >
                        {order.state}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-secondary">
                      {order.amend_count}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-secondary text-xs">
                      {formatElapsed(order.elapsed_ms)}
                    </td>
                    <td className="py-2.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleAction(order.id, 'pause')}
                          aria-label="Pause smart order"
                          className="p-1.5 rounded hover:bg-cream text-secondary hover:text-primary transition-colors"
                        >
                          <Pause size={14} />
                        </button>
                        <button
                          onClick={() => handleAction(order.id, 'resume')}
                          aria-label="Resume smart order"
                          className="p-1.5 rounded hover:bg-cream text-secondary hover:text-primary transition-colors"
                        >
                          <Play size={14} />
                        </button>
                        <button
                          onClick={() => handleAction(order.id, 'market')}
                          aria-label="Fill smart order at market"
                          className="p-1.5 rounded hover:bg-cream text-secondary hover:text-accent transition-colors"
                        >
                          <Zap size={14} />
                        </button>
                        <button
                          onClick={() => handleAction(order.id, 'cancel')}
                          aria-label="Cancel smart order"
                          className="p-1.5 rounded hover:bg-loss-bg text-secondary hover:text-loss transition-colors"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Order History */}
      <Card>
        <h3 className="text-sm font-semibold text-primary mb-4">History</h3>
        {historyOrders.length === 0 ? (
          <div className="text-sm text-secondary py-8 text-center">No order history</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white z-10">
                <tr className="border-b border-divider text-overline text-secondary uppercase tracking-wider">
                  <th className="text-left pb-2 pr-3">ID</th>
                  <th className="text-left pb-2 pr-3">Instrument</th>
                  <th className="text-left pb-2 pr-3">Direction</th>
                  <th className="text-right pb-2 pr-3">Amount</th>
                  <th className="text-left pb-2 pr-3">Algorithm</th>
                  <th className="text-left pb-2 pr-3">State</th>
                  <th className="text-right pb-2 pr-3">Amends</th>
                  <th className="text-right pb-2">Fee Mode</th>
                </tr>
              </thead>
              <tbody>
                {historyOrders.map((order) => (
                  <tr
                    key={order.id}
                    className="border-b border-divider/50 hover:bg-cream/50 transition-colors"
                  >
                    <td className="py-2.5 pr-3 font-mono text-xs text-secondary">
                      {order.id.slice(0, 8)}
                    </td>
                    <td className="py-2.5 pr-3 font-medium text-primary">
                      {order.instrument}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          order.direction === 'buy'
                            ? 'bg-profit-bg text-profit'
                            : 'bg-loss-bg text-loss'
                        }`}
                      >
                        {order.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono">{order.amount}</td>
                    <td className="py-2.5 pr-3 text-secondary">{order.algorithm}</td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          STATUS_BADGE[order.state] ?? 'bg-cream text-secondary'
                        }`}
                      >
                        {order.state}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-secondary">
                      {order.amend_count}
                    </td>
                    <td className="py-2.5 text-right font-mono text-secondary">
                      {order.fee_mode ?? '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default SmartOrders;
