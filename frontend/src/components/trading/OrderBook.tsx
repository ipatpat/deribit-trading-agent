import { useEffect, useMemo, useState } from 'react';
import { formatPrice } from '../../utils/format';
import { useRefreshInterval } from '../../stores/settings';

interface Level {
  price: number;
  size: number;
}

interface OrderBookProps {
  instrument: string;
  depth?: number;
}

function OrderBook({ instrument, depth = 7 }: OrderBookProps) {
  const [bids, setBids] = useState<Level[]>([]);
  const [asks, setAsks] = useState<Level[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshMs = useRefreshInterval('orderbook');

  useEffect(() => {
    let cancelled = false;

    async function fetchBook() {
      try {
        const res = await fetch(`/api/v1/orderbook?instrument=${instrument}&depth=${depth}`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        const rawBids: Level[] = (data.bids || []).map((b: any) => ({
          price: Array.isArray(b) ? b[0] : b.price,
          size: Array.isArray(b) ? b[1] : b.size,
        }));
        const rawAsks: Level[] = (data.asks || []).map((a: any) => ({
          price: Array.isArray(a) ? a[0] : a.price,
          size: Array.isArray(a) ? a[1] : a.size,
        }));
        setBids(rawBids.slice(0, depth));
        setAsks(rawAsks.slice(0, depth));
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchBook();
    const interval = setInterval(fetchBook, refreshMs ?? 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [instrument, refreshMs, depth]);

  const maxSize = useMemo(() => {
    const all = [...bids, ...asks];
    return Math.max(...all.map((l) => l.size), 1);
  }, [asks, bids]);

  const spread = asks.length > 0 && bids.length > 0 ? asks[0].price - bids[0].price : 0;
  const spreadPct = bids.length > 0 && bids[0].price > 0 ? spread / bids[0].price : 0;
  const decimals = instrument.startsWith('ETH') ? 2 : 2;

  if (loading) {
    return <div className="h-[240px] bg-cream rounded animate-pulse" />;
  }

  if (asks.length === 0 && bids.length === 0) {
    return <div className="text-[10px] text-secondary text-center py-4">No orderbook data</div>;
  }

  // Asks reversed: highest at top, lowest near spread
  const askRows = [...asks].slice(0, depth).reverse();
  const bidRows = bids.slice(0, depth);

  return (
    <div className="text-xs font-mono">
      {/* Header */}
      <div className="flex items-center justify-between text-secondary uppercase tracking-wider font-semibold px-2 py-1 bg-cream-light border-b border-divider text-[10px]">
        <span>Price</span>
        <span>Size</span>
      </div>

      {/* Asks (red) */}
      {askRows.map((row) => (
        <div key={row.price} className="relative flex items-center justify-between px-2 h-5">
          <div
            className="absolute right-0 top-0 bottom-0 bg-loss/8 rounded-sm"
            style={{ width: `${(row.size / maxSize) * 100}%` }}
          />
          <span className="relative text-loss">{formatPrice(row.price, decimals)}</span>
          <span className="relative text-primary">{row.size >= 1000 ? `${(row.size / 1000).toFixed(1)}k` : row.size >= 1 ? row.size.toFixed(0) : row.size.toFixed(2)}</span>
        </div>
      ))}

      {/* Spread */}
      <div className="flex items-center justify-center h-6 border-y border-divider/50 text-secondary">
        <span>Spread ${spread.toFixed(decimals)}</span>
        <span className="ml-1.5 text-disabled">({(spreadPct * 100).toFixed(3)}%)</span>
      </div>

      {/* Bids (green) */}
      {bidRows.map((row) => (
        <div key={row.price} className="relative flex items-center justify-between px-2 h-5">
          <div
            className="absolute right-0 top-0 bottom-0 bg-profit/8 rounded-sm"
            style={{ width: `${(row.size / maxSize) * 100}%` }}
          />
          <span className="relative text-profit">{formatPrice(row.price, decimals)}</span>
          <span className="relative text-primary">{row.size >= 1000 ? `${(row.size / 1000).toFixed(1)}k` : row.size >= 1 ? row.size.toFixed(0) : row.size.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export default OrderBook;
