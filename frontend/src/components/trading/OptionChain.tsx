import { useEffect, useState, useRef, useCallback } from 'react';
import { getOptionChain } from '../../api/client';
import type { OptionChainRow, Ticker } from '../../types/api';
import { formatPrice } from '../../utils/format';
import { usePolling } from '../../utils/usePolling';
import { useRefreshInterval } from '../../stores/settings';

// Match tailwind.config.ts accent token
const ACCENT = '#F05C00';
const ACCENT_RGBA = (alpha: number) => `rgba(240,92,0,${alpha})`;

interface OptionChainProps {
  currency: string;
  expiry: string;
  onSelectOption: (instrument: string, direction: 'buy' | 'sell') => void;
  onAddFutures?: (direction: 'buy' | 'sell') => void;
}

function fmtIv(ticker: any): string {
  if (!ticker) return '-';
  const iv = ticker.implied_volatility ?? ticker.iv ?? ticker.mark_iv;
  if (iv == null) return '-';
  return iv.toFixed(1) + '%';
}

function fmtDelta(ticker: any): string {
  if (!ticker) return '-';
  const delta = ticker.delta ?? ticker.greeks?.delta;
  if (delta == null) return '-';
  return delta.toFixed(2);
}

function TickerCells({
  ticker,
  maxVolume,
  onClickBid,
  onClickAsk,
}: {
  ticker: Ticker | null;
  maxVolume: number;
  onClickBid?: () => void;
  onClickAsk?: () => void;
}) {
  if (!ticker) {
    return (
      <>
        <td className="px-2 py-1.5 text-center text-disabled font-mono text-xs">-</td>
        <td className="px-2 py-1.5 text-center text-disabled font-mono text-xs">-</td>
        <td className="px-2 py-1.5 text-center text-disabled font-mono text-xs">-</td>
        <td className="px-2 py-1.5 text-center text-disabled font-mono text-xs">-</td>
        <td className="px-2 py-1.5 text-center font-mono text-xs">
          <div className="h-3 w-full bg-cream rounded" />
        </td>
      </>
    );
  }

  const vol = (ticker as any).volume_24h ?? 0;
  const volWidth = maxVolume > 0 ? (vol / maxVolume) * 100 : 0;

  return (
    <>
      <td
        className="px-2 py-1.5 text-center font-mono text-xs text-profit cursor-pointer hover:bg-profit-bg"
        role="button"
        tabIndex={0}
        onClick={onClickBid}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClickBid?.(); } }}
      >
        {formatPrice(ticker.best_bid_price, 4)}
      </td>
      <td
        className="px-2 py-1.5 text-center font-mono text-xs text-loss cursor-pointer hover:bg-loss-bg"
        role="button"
        tabIndex={0}
        onClick={onClickAsk}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClickAsk?.(); } }}
      >
        {formatPrice(ticker.best_ask_price, 4)}
      </td>
      <td className="px-2 py-1.5 text-center font-mono text-xs text-secondary">
        {fmtIv(ticker)}
      </td>
      <td className="px-2 py-1.5 text-center font-mono text-xs text-secondary">
        {fmtDelta(ticker)}
      </td>
      <td className="px-2 py-1.5 w-16">
        <div className="relative h-3 w-full bg-cream rounded overflow-hidden">
          <div
            className="absolute inset-y-0 left-0 bg-accent/20 rounded"
            style={{ width: `${Math.min(volWidth, 100)}%` }}
          />
        </div>
      </td>
    </>
  );
}

function OptionChain({ currency, expiry, onSelectOption, onAddFutures }: OptionChainProps) {
  const [rows, setRows] = useState<OptionChainRow[]>([]);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const priceRowRef = useRef<HTMLTableRowElement>(null);
  const refreshMs = useRefreshInterval('optionChain');

  const fetchChain = useCallback((showLoading = false) => {
    if (!currency || !expiry) return;
    if (showLoading) setLoading(true);
    getOptionChain(currency, expiry)
      .then((data: any) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]))
      .finally(() => { if (showLoading) setLoading(false); });
  }, [currency, expiry]);

  useEffect(() => {
    fetchChain(true);
  }, [fetchChain]);

  usePolling(() => {
    fetchChain(false);
  }, refreshMs);

  useEffect(() => {
    if (!loading && priceRowRef.current && scrollRef.current) {
      setTimeout(() => {
        const container = scrollRef.current!;
        const row = priceRowRef.current!;
        const rowTop = row.offsetTop;
        const containerHeight = container.clientHeight;
        container.scrollTop = rowTop - containerHeight / 2;
      }, 50);
    }
  }, [loading, rows]);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-8 bg-cream rounded animate-pulse" />
        ))}
      </div>
    );
  }

  if (rows.length === 0) {
    return <div className="text-sm text-secondary py-8 text-center">No option data available</div>;
  }

  const underlyingPrice =
    (rows.find((r: any) => r.call)?.call as any)?.underlying_price ??
    (rows.find((r: any) => r.put)?.put as any)?.underlying_price ??
    0;

  let priceInsertIndex = -1;
  for (let i = 0; i < rows.length - 1; i++) {
    if (rows[i].strike <= underlyingPrice && rows[i + 1].strike > underlyingPrice) {
      priceInsertIndex = i + 1;
      break;
    }
  }
  if (underlyingPrice < rows[0].strike) priceInsertIndex = 0;
  if (underlyingPrice >= rows[rows.length - 1].strike) priceInsertIndex = rows.length;

  const atmStrike = rows.reduce((prev, curr) =>
    Math.abs(curr.strike - underlyingPrice) < Math.abs(prev.strike - underlyingPrice) ? curr : prev
  ).strike;

  const allTickers = rows.flatMap((r: any) => [r.call, r.put].filter(Boolean));
  const maxVolume = Math.max(...allTickers.map((t: any) => t.volume_24h ?? 0), 1);

  const atmRowIndex = rows.findIndex((r) => r.strike === atmStrike);

  const items: { type: 'row' | 'price'; row?: any; index?: number }[] = [];
  for (let i = 0; i < rows.length; i++) {
    if (i === priceInsertIndex) {
      items.push({ type: 'price' });
    }
    items.push({ type: 'row', row: rows[i], index: i });
  }
  if (priceInsertIndex === rows.length) {
    items.push({ type: 'price' });
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead className="sticky top-0 bg-white z-10">
          <tr className="border-b border-divider/50 text-secondary">
            <th colSpan={5} className="pt-4 pb-2 text-center text-[10px] font-bold text-profit uppercase tracking-widest">
              Calls
            </th>
            <th className="pt-4 pb-2 text-center text-[10px] font-bold text-primary uppercase tracking-widest">Strike</th>
            <th colSpan={5} className="pt-4 pb-2 text-center text-[10px] font-bold text-loss uppercase tracking-widest">
              Puts
            </th>
          </tr>
          <tr className="border-b border-divider text-[10px] text-secondary uppercase tracking-widest bg-white">
            <th className="px-2 py-1.5 text-center font-semibold">Bid</th>
            <th className="px-2 py-1.5 text-center font-semibold">Ask</th>
            <th className="px-2 py-1.5 text-center font-semibold">IV%</th>
            <th className="px-2 py-1.5 text-center font-semibold">Delta</th>
            <th className="px-2 py-1.5 text-center font-semibold">Vol</th>
            <th className="px-2 py-1.5 text-center font-semibold" />
            <th className="px-2 py-1.5 text-center font-semibold">Bid</th>
            <th className="px-2 py-1.5 text-center font-semibold">Ask</th>
            <th className="px-2 py-1.5 text-center font-semibold">IV%</th>
            <th className="px-2 py-1.5 text-center font-semibold">Delta</th>
            <th className="px-2 py-1.5 text-center font-semibold">Vol</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            if (item.type === 'price') {
              return (
                <tr
                  key="price-indicator"
                  ref={priceRowRef}
                  className="group h-7"
                >
                  <td colSpan={5} className="py-0" />
                  <td className="py-0 text-center">
                    <div className="flex items-center justify-center gap-2 px-2 h-full">
                      {onAddFutures && (
                        <button
                          onClick={() => onAddFutures('sell')}
                          className="px-2 py-0.5 rounded text-[10px] font-semibold text-loss bg-loss-bg opacity-0 group-hover:opacity-100 transition-opacity duration-200"
                        >
                          Sell
                        </button>
                      )}
                      <span className="text-[11px] font-semibold text-primary font-mono whitespace-nowrap bg-accent/[0.06] rounded-md px-2 py-0.5">
                        {formatPrice(underlyingPrice, 0)}
                      </span>
                      {onAddFutures && (
                        <button
                          onClick={() => onAddFutures('buy')}
                          className="px-2 py-0.5 rounded text-[10px] font-semibold text-profit bg-profit-bg opacity-0 group-hover:opacity-100 transition-opacity duration-200"
                        >
                          Buy
                        </button>
                      )}
                    </div>
                  </td>
                  <td colSpan={5} className="py-0" />
                </tr>
              );
            }

            const row = item.row;
            const isAtm = row.strike === atmStrike;
            const strikeDist = atmRowIndex >= 0 && item.index != null ? Math.abs(item.index - atmRowIndex) : Infinity;
            const atmBand = isAtm ? 'bg-accent/[0.06]' : strikeDist <= 2 ? 'bg-accent/[0.03]' : '';
            return (
              <tr
                key={row.strike}
                className={`border-b border-divider/30 hover:bg-cream-dark/50 transition-colors ${atmBand}`}
              >
                <TickerCells
                  ticker={row.call}
                  maxVolume={maxVolume}
                  onClickBid={() => {
                    if (row.call) onSelectOption((row.call as any).instrument_name, 'sell');
                  }}
                  onClickAsk={() => {
                    if (row.call) onSelectOption((row.call as any).instrument_name, 'buy');
                  }}
                />
                <td className="px-3 py-1.5 text-center font-mono text-xs font-semibold text-primary">
                  {formatPrice(row.strike, 0)}
                </td>
                <TickerCells
                  ticker={row.put}
                  maxVolume={maxVolume}
                  onClickBid={() => {
                    if (row.put) onSelectOption((row.put as any).instrument_name, 'sell');
                  }}
                  onClickAsk={() => {
                    if (row.put) onSelectOption((row.put as any).instrument_name, 'buy');
                  }}
                />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default OptionChain;
