import { useState, useEffect, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import {
  calculatePayoff,
  type PayoffLeg,
  type PayoffResult,
} from '../../api/client';

function isFuturesInstrument(instrument: string): boolean {
  const parts = instrument.split('-');
  return parts.length === 2;
}

function futuresLabel(instrument: string): string {
  const parts = instrument.split('-');
  return parts[1] === 'PERPETUAL' ? 'PERP' : parts[1];
}

interface PayoffBuilderProps {
  legs: PayoffLeg[];
  onRemoveLeg: (index: number) => void;
  onToggleDirection: (index: number) => void;
  onChangeAmount: (index: number, amount: number) => void;
  onTradeLeg?: (instrument: string, direction: 'buy' | 'sell') => void;
}

function PayoffBuilder({
  legs,
  onRemoveLeg,
  onToggleDirection,
  onChangeAmount,
  onTradeLeg,
}: PayoffBuilderProps) {
  const [unit, setUnit] = useState<'btc' | 'usd'>('btc');
  const [result, setResult] = useState<PayoffResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (legs.length === 0) {
      setResult(null);
      setError(null);
      return;
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(() => {
      setLoading(true);
      setError(null);
      calculatePayoff(legs)
        .then((data) => setResult(data))
        .catch((err) => setError(err.message ?? 'Failed to calculate payoff'))
        .finally(() => setLoading(false));
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [legs]);

  if (legs.length === 0) {
    return (
      <div className="flex items-center justify-center h-[300px] text-secondary text-xs">
        Click bid/ask in the option chain to build a combo
      </div>
    );
  }

  const points = result
    ? unit === 'btc'
      ? result.payoff_btc
      : result.payoff_usd
    : [];
  const summary = result?.summary;
  const underlyingPrice = result?.underlying_price ?? 0;

  // Extract strike prices from leg instrument names
  const strikeSet = new Set<number>();
  for (const leg of legs) {
    const parts = leg.instrument.split('-');
    if (parts.length >= 4) {
      const s = Number(parts[2]);
      if (!isNaN(s)) strikeSet.add(s);
    }
  }
  const strikes = Array.from(strikeSet);

  // Build chart
  const prices = points.map((p) => p.price);
  const pnls = points.map((p) => p.pnl);

  const profitData = pnls.map((v) => (v >= 0 ? v : 0));
  const lossData = pnls.map((v) => (v < 0 ? v : 0));

  const breakevenPrices = summary?.breakeven ?? [];
  const maxLoss = unit === 'btc' ? summary?.max_loss_btc : summary?.max_loss_usd;

  const fmtVal = (v: number | undefined) => {
    if (v == null) return '-';
    if (!isFinite(v)) return 'Unlimited';
    const abs = Math.abs(v);
    if (abs === 0) return '0';
    if (abs < 0.0001) return v.toFixed(8);
    if (abs < 0.01) return v.toFixed(6);
    if (abs < 1) return v.toFixed(4);
    return v.toFixed(2);
  };

  const markLines: any[] = [];

  // Strike lines (dashed gray)
  for (const s of strikes) {
    markLines.push({
      xAxis: s,
      label: { show: false },
      lineStyle: { color: '#939191', type: 'dashed', width: 1 },
    });
  }

  // Breakeven lines (dashed green)
  for (const bep of breakevenPrices) {
    markLines.push({
      xAxis: bep,
      label: {
        formatter: `BE: ${bep.toFixed(0)}`,
        fontSize: 9,
        position: 'start',
        color: '#049554',
      },
      lineStyle: { color: '#049554', type: 'dashed', width: 1 },
    });
  }

  // Underlying price (solid orange)
  if (underlyingPrice > 0) {
    markLines.push({
      xAxis: underlyingPrice,
      label: {
        formatter: `Spot: ${underlyingPrice.toFixed(0)}`,
        fontSize: 9,
        position: 'start',
        color: '#E8850C',
      },
      lineStyle: { color: '#E8850C', type: 'solid', width: 1.5 },
    });
  }

  // Max loss horizontal line
  const horizontalLines: any[] = [];
  if (maxLoss != null && maxLoss < 0 && isFinite(maxLoss)) {
    horizontalLines.push({
      yAxis: maxLoss,
      label: {
        formatter: `Max Loss: ${fmtVal(maxLoss)}`,
        fontSize: 9,
        position: 'insideStartTop',
        color: '#FF3B30',
      },
      lineStyle: { color: '#FF3B30', type: 'dashed', width: 1 },
    });
  }

  const allMarkLines = [...markLines, ...horizontalLines];

  const chartOption: EChartsOption = {
    grid: { top: 30, right: 16, bottom: 36, left: 56 },
    xAxis: {
      type: 'category',
      data: prices,
      name: 'Price at Expiry',
      nameLocation: 'middle',
      nameGap: 22,
      nameTextStyle: { fontSize: 9, color: '#939191' },
      axisLabel: {
        fontSize: 9,
        color: '#939191',
        interval: Math.max(1, Math.floor(prices.length / 6)),
      },
      axisLine: { lineStyle: { color: '#E4DFD6' } },
    },
    yAxis: {
      type: 'value',
      name: `P&L (${unit.toUpperCase()})`,
      nameLocation: 'middle',
      nameGap: 44,
      nameTextStyle: { fontSize: 9, color: '#939191' },
      axisLabel: { fontSize: 9, color: '#939191' },
      splitLine: { lineStyle: { color: '#F0EDE6' } },
    },
    series: [
      {
        type: 'line',
        data: profitData,
        stack: 'pnl',
        areaStyle: { color: 'rgba(4, 149, 84, 0.2)' },
        lineStyle: { color: '#049554', width: 2 },
        itemStyle: { color: '#049554' },
        symbol: 'none',
        markLine:
          allMarkLines.length > 0
            ? { silent: true, symbol: 'none', data: allMarkLines }
            : undefined,
      },
      {
        type: 'line',
        data: lossData,
        stack: 'pnl2',
        areaStyle: { color: 'rgba(255, 59, 48, 0.2)' },
        lineStyle: { color: '#FF3B30', width: 2 },
        itemStyle: { color: '#FF3B30' },
        symbol: 'none',
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        const idx = p.dataIndex;
        return `Price: ${prices[idx]}<br/>P&L: ${pnls[idx]?.toFixed(4) ?? '-'} ${unit.toUpperCase()}`;
      },
    },
  };

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-primary">Payoff Builder</h3>
        <div className="flex gap-1 bg-cream rounded p-0.5">
          {(['btc', 'usd'] as const).map((u) => (
            <button
              key={u}
              onClick={() => setUnit(u)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                unit === u
                  ? 'bg-primary text-white'
                  : 'text-secondary hover:text-primary'
              }`}
            >
              {u.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Legs list */}
      <div className="space-y-1">
        {legs.map((leg, i) => (
          <div
            key={`${leg.instrument}-${i}`}
            className="flex items-center gap-2 px-2 py-1 bg-cream rounded text-[10px]"
          >
            <button
              onClick={() => onToggleDirection(i)}
              className={`px-1.5 py-0.5 rounded font-semibold uppercase ${
                leg.direction === 'buy'
                  ? 'bg-profit/10 text-profit'
                  : 'bg-loss/10 text-loss'
              }`}
            >
              {leg.direction}
            </button>
            {isFuturesInstrument(leg.instrument) ? (
              <span className="flex items-center gap-1 flex-1 truncate">
                <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 text-[9px] font-semibold">
                  {futuresLabel(leg.instrument)}
                </span>
                <span className="font-mono text-primary text-[10px]">
                  {leg.instrument.split('-')[0]}
                </span>
              </span>
            ) : (
              <span className="font-mono text-primary flex-1 truncate">
                {leg.instrument}
              </span>
            )}
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={leg.amount}
              onChange={(e) =>
                onChangeAmount(i, Math.max(0.1, Number(e.target.value)))
              }
              className="w-12 px-1 py-0.5 text-center bg-white border border-divider rounded font-mono text-[10px]"
            />
            {onTradeLeg && (
              <button
                onClick={() => onTradeLeg(leg.instrument, leg.direction)}
                className="px-2 py-1 rounded text-[10px] font-bold bg-accent text-white hover:bg-accent/90 transition-colors"
                title="Trade this leg"
              >
                Trade
              </button>
            )}
            <button
              onClick={() => onRemoveLeg(i)}
              className="text-secondary hover:text-loss transition-colors px-1"
              title="Remove leg"
            >
              x
            </button>
          </div>
        ))}
      </div>

      {/* Chart */}
      {loading && (
        <div className="h-[250px] flex items-center justify-center text-secondary text-xs">
          Calculating...
        </div>
      )}
      {error && (
        <div className="h-[250px] flex items-center justify-center text-loss text-xs">
          {error}
        </div>
      )}
      {!loading && !error && points.length > 0 && (
        <ReactECharts
          option={chartOption}
          style={{ height: 250 }}
          notMerge
        />
      )}

      {/* Summary */}
      {summary && !loading && (
        <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-[10px]">
          <div>
            <span className="text-secondary">Max Profit</span>
            <p className="font-mono text-profit">
              {fmtVal(unit === 'btc' ? summary.max_profit_btc : summary.max_profit_usd)}
            </p>
          </div>
          <div>
            <span className="text-secondary">Max Loss</span>
            <p className="font-mono text-loss">
              {fmtVal(
                unit === 'btc'
                  ? summary.max_loss_btc
                  : summary.max_loss_usd,
              )}
            </p>
          </div>
          <div>
            <span className="text-secondary">Breakeven</span>
            <p className="font-mono text-primary">
              {breakevenPrices.length > 0
                ? breakevenPrices.map((b) => b.toFixed(0)).join(', ')
                : '-'}
            </p>
          </div>
          <div>
            <span className="text-secondary">R/R Ratio</span>
            <p className="font-mono text-primary">
              {fmtVal(summary.risk_reward_ratio)}
            </p>
          </div>
          <div>
            <span className="text-secondary">Net Delta</span>
            <p className="font-mono text-primary">
              {fmtVal(summary.net_delta)}
            </p>
          </div>
          <div>
            <span className="text-secondary">Net Theta</span>
            <p className="font-mono text-primary">
              {fmtVal(summary.net_theta)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default PayoffBuilder;
