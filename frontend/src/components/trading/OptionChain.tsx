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
  /** "compact" = 24px row, dense; "comfortable" = 32px row, more breathing (default) */
  density?: 'compact' | 'comfortable';
  /** Default ATM ± 10 strikes. Pass true to show all strikes. */
  showAll?: boolean;
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
  cellPad,
  onClickBid,
  onClickAsk,
}: {
  ticker: Ticker | null;
  maxVolume: number;
  cellPad: string;
  onClickBid?: () => void;
  onClickAsk?: () => void;
}) {
  if (!ticker) {
    return (
      <>
        <td className={`${cellPad} text-center text-disabled font-mono`}>-</td>
        <td className={`${cellPad} text-center text-disabled font-mono`}>-</td>
        <td className={`${cellPad} text-center text-disabled font-mono`}>-</td>
        <td className={`${cellPad} text-center text-disabled font-mono`}>-</td>
        <td className={`${cellPad} text-center font-mono`}>
          <div className="h-2.5 w-full bg-cream rounded" />
        </td>
      </>
    );
  }

  const vol = (ticker as any).volume_24h ?? 0;
  const volWidth = maxVolume > 0 ? (vol / maxVolume) * 100 : 0;

  return (
    <>
      <td
        className={`${cellPad} text-center font-mono text-profit cursor-pointer hover:bg-profit-bg`}
        role="button"
        tabIndex={0}
        onClick={onClickBid}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClickBid?.(); } }}
      >
        {formatPrice(ticker.best_bid_price, 4)}
      </td>
      <td
        className={`${cellPad} text-center font-mono text-loss cursor-pointer hover:bg-loss-bg`}
        role="button"
        tabIndex={0}
        onClick={onClickAsk}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClickAsk?.(); } }}
      >
        {formatPrice(ticker.best_ask_price, 4)}
      </td>
      <td className={`${cellPad} text-center font-mono text-secondary`}>
        {fmtIv(ticker)}
      </td>
      <td className={`${cellPad} text-center font-mono text-secondary`}>
        {fmtDelta(ticker)}
      </td>
      <td className={`${cellPad} w-12`}>
        <div className="relative h-2.5 w-full bg-cream rounded overflow-hidden">
          <div
            className="absolute inset-y-0 left-0 bg-accent/20 rounded"
            style={{ width: `${Math.min(volWidth, 100)}%` }}
          />
        </div>
      </td>
    </>
  );
}

const ATM_WINDOW = 10;

function OptionChain({
  currency,
  expiry,
  onSelectOption,
  density = 'comfortable',
  showAll = false,
}: OptionChainProps) {
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

  // Default-narrow: ATM ± ATM_WINDOW strikes; full chain when showAll=true
  const sliceStart = showAll ? 0 : Math.max(0, atmRowIndex - ATM_WINDOW);
  const sliceEnd = showAll ? rows.length : Math.min(rows.length, atmRowIndex + ATM_WINDOW + 1);
  const visibleRows = rows.slice(sliceStart, sliceEnd);
  const adjustedPriceIndex = priceInsertIndex - sliceStart;

  const items: { type: 'row' | 'price'; row?: any; index?: number }[] = [];
  for (let i = 0; i < visibleRows.length; i++) {
    if (i === adjustedPriceIndex) {
      items.push({ type: 'price' });
    }
    items.push({ type: 'row', row: visibleRows[i], index: sliceStart + i });
  }
  if (adjustedPriceIndex === visibleRows.length) {
    items.push({ type: 'price' });
  }

  // Density-driven sizing tokens
  const isCompact = density === 'compact';
  const cellPad = isCompact
    ? 'px-1.5 py-0.5 text-[12px] leading-[14px]'
    : 'px-2 py-1.5 text-[12px] leading-[18px]';
  const rowHeight = isCompact ? 'h-6' : 'h-8';
  const priceRowHeight = isCompact ? 'h-3' : 'h-5';

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto overflow-x-auto">
      <table className="w-full font-mono">
        <thead className="sticky top-0 bg-white z-10">
          <tr className="border-b border-divider/50 text-secondary">
            <th colSpan={5} className="pt-2 pb-1 text-center text-[10px] font-bold text-profit uppercase tracking-widest">
              Calls
            </th>
            <th className="pt-2 pb-1 text-center text-[10px] font-bold text-primary uppercase tracking-widest">Strike</th>
            <th colSpan={5} className="pt-2 pb-1 text-center text-[10px] font-bold text-loss uppercase tracking-widest">
              Puts
            </th>
          </tr>
          <tr className="border-b border-divider text-[10px] text-secondary uppercase tracking-widest bg-white">
            <th className="px-1.5 py-1 text-center font-semibold">Bid</th>
            <th className="px-1.5 py-1 text-center font-semibold">Ask</th>
            <th className="px-1.5 py-1 text-center font-semibold">IV%</th>
            <th className="px-1.5 py-1 text-center font-semibold">Delta</th>
            <th className="px-1.5 py-1 text-center font-semibold">Vol</th>
            <th className="px-1.5 py-1 text-center font-semibold" />
            <th className="px-1.5 py-1 text-center font-semibold">Bid</th>
            <th className="px-1.5 py-1 text-center font-semibold">Ask</th>
            <th className="px-1.5 py-1 text-center font-semibold">IV%</th>
            <th className="px-1.5 py-1 text-center font-semibold">Delta</th>
            <th className="px-1.5 py-1 text-center font-semibold">Vol</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            if (item.type === 'price') {
              return (
                <tr
                  key="price-indicator"
                  ref={priceRowRef}
                  className="h-4"
                >
                  <td colSpan={11} className="relative h-4 p-0">
                    {/* Dashed line drawn via absolute div to bypass border-collapse:collapse
                        which would otherwise merge with neighbor row's solid divider and win. */}
                    <div
                      aria-hidden="true"
                      className="absolute inset-x-0 top-1/2 border-t border-dashed border-accent/60 pointer-events-none"
                    />
                    <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-cream-light text-[10px] font-mono font-semibold text-accent px-1.5 py-0.5 whitespace-nowrap z-10">
                      {formatPrice(underlyingPrice, 0)}
                    </span>
                  </td>
                </tr>
              );
            }

            const row = item.row;
            // First row below the price marker line — gives the "below-ATM" block a clear top border
            const isFirstBelowMarker = item.index === priceInsertIndex;
            const blockTop = isFirstBelowMarker ? 'border-t border-divider-strong' : '';
            return (
              <tr
                key={row.strike}
                className={`${rowHeight} border-b border-divider/30 hover:bg-cream-dark/50 transition-colors ${blockTop}`}
              >
                <TickerCells
                  ticker={row.call}
                  maxVolume={maxVolume}
                  cellPad={cellPad}
                  onClickBid={() => {
                    if (row.call) onSelectOption((row.call as any).instrument_name, 'sell');
                  }}
                  onClickAsk={() => {
                    if (row.call) onSelectOption((row.call as any).instrument_name, 'buy');
                  }}
                />
                <td className={`${cellPad} text-center font-semibold text-primary`}>
                  {formatPrice(row.strike, 0)}
                </td>
                <TickerCells
                  ticker={row.put}
                  maxVolume={maxVolume}
                  cellPad={cellPad}
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
