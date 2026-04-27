import { useRef, useState } from 'react';
import Card from '../components/common/Card';
import Skeleton from '../components/common/Skeleton';
import EquityCurve from '../components/charts/EquityCurve';
import { type PortfolioOverview, getPortfolioOverview } from '../api/client';
import { formatPrice, formatUsd, formatCompactUsd } from '../utils/format';
import { usePolling } from '../utils/usePolling';
import { useRefreshInterval } from '../stores/settings';
import { useToastStore } from '../stores/toast';

function Dashboard() {
  const [data, setData] = useState<PortfolioOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadedOnce = useRef(false);
  const refreshMs = useRefreshInterval('dashboard');
  const showToast = useToastStore((s) => s.show);

  const fetchData = () => {
    getPortfolioOverview()
      .then((d) => {
        setData(d);
        setError(null);
        if (!loadedOnce.current) {
          loadedOnce.current = true;
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!loadedOnce.current) {
          loadedOnce.current = true;
          setLoading(false);
        }
        setError((err as Error).message || 'Failed to load portfolio data');
        showToast('error', 'Failed to load portfolio data');
      });
  };

  usePolling(fetchData, refreshMs);

  const btc = data?.accounts?.BTC;
  const eth = data?.accounts?.ETH;
  const btcPrice = data?.index_prices?.BTC ?? 0;
  const ethPrice = data?.index_prices?.ETH ?? 0;
  const totalUsd = data?.total_usd ?? 0;
  const positions = data?.positions ?? [];

  const totalPnlUsd = (btc?.total_pl ?? 0) * btcPrice + (eth?.total_pl ?? 0) * ethPrice;
  const todayPnlUsd =
    ((btc?.session_upl ?? 0) + (btc?.session_rpl ?? 0)) * btcPrice +
    ((eth?.session_upl ?? 0) + (eth?.session_rpl ?? 0)) * ethPrice;

  const totalMarginUsd = (btc?.initial_margin ?? 0) * btcPrice + (eth?.initial_margin ?? 0) * ethPrice;
  const totalAvailUsd = (btc?.available_funds ?? 0) * btcPrice + (eth?.available_funds ?? 0) * ethPrice;
  const marginPct = totalUsd > 0 ? totalMarginUsd / totalUsd : 0;
  const netDelta = (btc?.delta_total ?? 0) + (eth?.delta_total ?? 0);

  const marginBarColor = marginPct > 0.8 ? 'bg-loss' : marginPct > 0.5 ? 'bg-accent' : 'bg-profit';

  return (
    <div className="dashboard-mode space-y-6">

      {/* Hero numbers */}
      <div className="flex items-end justify-between px-1">
        <div>
          <div className="text-sm text-secondary uppercase tracking-wider font-semibold">Total Equity</div>
          {loading ? (
            <Skeleton className="h-10 w-48 mt-1" />
          ) : (
            <div className="text-3xl font-semibold font-mono text-primary tracking-tight mt-1">
              {formatCompactUsd(totalUsd)}
            </div>
          )}
        </div>
        {!loading && (
          <div className="flex gap-8 items-end">
            <div className="text-right">
              <div className="text-xs text-secondary uppercase tracking-wider font-semibold">Total PnL</div>
              <div className={`text-xl font-semibold font-mono mt-1 ${totalPnlUsd >= 0 ? 'text-profit' : 'text-loss'}`}>
                {formatUsd(totalPnlUsd)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-secondary uppercase tracking-wider font-semibold">Today</div>
              <div className={`text-base font-semibold font-mono mt-1 ${todayPnlUsd >= 0 ? 'text-profit' : 'text-loss'}`}>
                {formatUsd(todayPnlUsd)}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && !loading && (
        <div className="flex items-center justify-between bg-loss-bg border border-loss/20 rounded-card px-5 py-4">
          <span className="text-sm text-loss font-medium">{error}</span>
          <button
            onClick={fetchData}
            className="text-sm font-semibold text-loss hover:underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Four-metric bar */}
      <div className="grid grid-cols-4 gap-6">
        {/* BTC */}
        <Card className="px-5 py-5">
          <div className="text-xs text-secondary uppercase tracking-wider font-semibold">BTC</div>
          {loading ? <Skeleton className="h-6 w-28 mt-2" /> : (
            <div className="mt-2">
              <div className="text-lg font-semibold font-mono text-primary">
                {formatPrice(btc?.equity, 4)}
              </div>
              <div className="text-sm text-secondary font-mono mt-0.5">
                &asymp;{formatCompactUsd((btc?.equity ?? 0) * btcPrice)}
              </div>
              <div className={`text-sm font-mono mt-1.5 font-medium ${(btc?.total_pl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>
                {(btc?.total_pl ?? 0) >= 0 ? '+' : '-'}{formatPrice(Math.abs(btc?.total_pl ?? 0), 4)} / {formatUsd((btc?.total_pl ?? 0) * btcPrice)}
              </div>
            </div>
          )}
        </Card>

        {/* ETH */}
        <Card className="px-5 py-5">
          <div className="text-xs text-secondary uppercase tracking-wider font-semibold">ETH</div>
          {loading ? <Skeleton className="h-6 w-28 mt-2" /> : (
            <div className="mt-2">
              <div className="text-lg font-semibold font-mono text-primary">
                {formatPrice(eth?.equity, 4)}
              </div>
              <div className="text-sm text-secondary font-mono mt-0.5">
                &asymp;{formatCompactUsd((eth?.equity ?? 0) * ethPrice)}
              </div>
              <div className={`text-sm font-mono mt-1.5 font-medium ${(eth?.total_pl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>
                {(eth?.total_pl ?? 0) >= 0 ? '+' : '-'}{formatPrice(Math.abs(eth?.total_pl ?? 0), 4)} / {formatUsd((eth?.total_pl ?? 0) * ethPrice)}
              </div>
            </div>
          )}
        </Card>

        {/* Margin */}
        <Card className="px-5 py-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-secondary uppercase tracking-wider font-semibold">Margin</span>
              {!loading && (
                <span className="text-sm font-mono font-semibold text-primary">{(marginPct * 100).toFixed(1)}%</span>
              )}
            </div>
            {loading ? <Skeleton className="h-6 w-full mt-2" /> : (
              <div className="mt-3">
                <div className="h-2 bg-cream-dark rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${marginBarColor}`}
                    style={{ width: `${Math.min(marginPct * 100, 100)}%` }}
                  />
                </div>
                <div className="flex justify-between mt-2 text-xs font-mono text-secondary">
                  <span>{formatCompactUsd(totalMarginUsd)} used</span>
                  <span>{formatCompactUsd(totalAvailUsd)} avail</span>
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Delta */}
        <Card className="px-5 py-5">
          <div className="text-xs text-secondary uppercase tracking-wider font-semibold">Net Delta</div>
          {loading ? <Skeleton className="h-6 w-16 mt-2" /> : (
            <div className="mt-2">
              <div className="text-lg font-semibold font-mono text-primary">
                {netDelta.toFixed(4)}
              </div>
              <div className="text-sm text-secondary mt-1 font-medium">
                {netDelta > 0 ? 'Net Long' : netDelta < 0 ? 'Net Short' : 'Neutral'}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Equity Curve */}
      <Card className="p-5">
        <EquityCurve btcPrice={btcPrice} ethPrice={ethPrice} />
      </Card>

      {/* Positions */}
      <Card className="p-5">
        <div className="text-sm text-primary uppercase tracking-wider font-semibold mb-4">
          Open Positions
        </div>
        {loading ? (
          <div className="space-y-3">
            {[1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : positions.length === 0 ? (
          <div className="text-base text-secondary py-8 text-center">No open positions</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white z-10">
                <tr className="border-b border-divider text-xs text-secondary uppercase tracking-wider">
                  <th className="text-left pb-3 pr-4 font-semibold">Instrument</th>
                  <th className="text-left pb-3 pr-4 font-semibold">Dir</th>
                  <th className="text-right pb-3 pr-4 font-semibold">Size</th>
                  <th className="text-right pb-3 pr-4 font-semibold">Entry</th>
                  <th className="text-right pb-3 pr-4 font-semibold">Mark</th>
                  <th className="text-right pb-3 pr-4 font-semibold">Total PnL</th>
                  <th className="text-right pb-3 pr-4 font-semibold">Lev</th>
                  <th className="text-right pb-3 font-semibold">Delta</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos: any) => {
                  const cur = pos.instrument_name?.startsWith('ETH') ? 'ETH' : 'BTC';
                  const idx = cur === 'ETH' ? ethPrice : btcPrice;
                  const pnl = pos.total_profit_loss ?? pos.floating_profit_loss ?? 0;
                  const pnlColor = pnl >= 0 ? 'text-profit' : 'text-loss';
                  const pnlSign = pnl >= 0 ? '+' : '-';
                  return (
                    <tr key={pos.instrument_name} className="border-b border-divider/50 hover:bg-cream/30 transition-colors">
                      <td className="py-3 pr-4 font-semibold text-primary">{pos.instrument_name}</td>
                      <td className="py-3 pr-4">
                        <span className={`inline-block px-2 py-1 rounded text-xs font-bold ${
                          pos.direction === 'buy' ? 'bg-profit-bg text-profit' : 'bg-loss-bg text-loss'
                        }`}>
                          {pos.direction?.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-right font-mono font-medium">{pos.size}</td>
                      <td className="py-3 pr-4 text-right font-mono">{formatPrice(pos.average_price)}</td>
                      <td className="py-3 pr-4 text-right font-mono">{formatPrice(pos.mark_price)}</td>
                      <td className="py-3 pr-4 text-right font-mono">
                        <div className={`font-medium ${pnlColor}`}>
                          {pnlSign}{Math.abs(pnl).toFixed(4)} {cur}
                        </div>
                        <div className={`text-xs mt-0.5 ${pnlColor}`}>
                          {formatUsd(pnl * idx)}
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-right font-mono text-secondary">
                        {pos.leverage ? `${pos.leverage}x` : '-'}
                      </td>
                      <td className="py-3 text-right font-mono text-secondary">
                        {(pos.delta ?? 0).toFixed(4)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default Dashboard;
