import { useEffect, useState, useCallback, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { getEquityCurve } from '../../api/client';
import { usePolling } from '../../utils/usePolling';
import { useRefreshInterval } from '../../stores/settings';
import { CHART, CHART_RGBA } from '../../utils/chartColors';
import {
  pickAxisFormatter,
  USD_PRESET,
  BTC_PRESET,
  ETH_PRESET,
} from '../../utils/axisFormat';
import { isEquityFlat } from '../../utils/equityFlat';

const TIME_RANGES = ['1h', '1d', '7d', '30d'] as const;
type Unit = 'BTC' | 'ETH' | 'USD';

interface EquityCurveProps {
  btcPrice?: number;
  ethPrice?: number;
}

function EquityCurve({ btcPrice = 0, ethPrice = 0 }: EquityCurveProps) {
  const [activeRange, setActiveRange] = useState(1);
  const [unit, setUnit] = useState<Unit>('BTC');
  const [btcData, setBtcData] = useState<{ time: number; value: number }[]>([]);
  const [ethData, setEthData] = useState<{ time: number; value: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const activeRangeRef = useRef(1);
  const refreshMs = useRefreshInterval('equityCurve');

  const fetchData = useCallback(async (period: string, showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const [btcResult, ethResult] = await Promise.all([
        getEquityCurve(period, 'BTC'),
        getEquityCurve(period, 'ETH'),
      ]);
      const parse = (r: any) =>
        ((r as any).data as any[] || []).map((p: any) => ({
          time: p.bucket_time ?? p.timestamp ?? 0,
          value: p.avg_equity ?? p.equity ?? 0,
        }));
      setBtcData(parse(btcResult));
      setEthData(parse(ethResult));
    } catch {
      setBtcData([]);
      setEthData([]);
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    activeRangeRef.current = activeRange;
    fetchData(TIME_RANGES[activeRange]);
  }, [activeRange, fetchData]);

  usePolling(() => {
    fetchData(TIME_RANGES[activeRangeRef.current], false);
  }, refreshMs);

  // Build chart data based on unit
  let chartData: [number, number][] = [];
  let yFormatter: (v: number) => string;
  let tooltipFormatter: (val: number) => string;
  let seriesValues: number[] = [];

  if (unit === 'BTC') {
    chartData = btcData.map((d) => [d.time, d.value]);
    seriesValues = btcData.map((d) => d.value);
    const axis = pickAxisFormatter(seriesValues, BTC_PRESET);
    yFormatter = axis.format;
    const tipDecimals = Math.max(axis.decimals, 4);
    tooltipFormatter = (v) => `${v.toFixed(tipDecimals)} BTC`;
  } else if (unit === 'ETH') {
    chartData = ethData.map((d) => [d.time, d.value]);
    seriesValues = ethData.map((d) => d.value);
    const axis = pickAxisFormatter(seriesValues, ETH_PRESET);
    yFormatter = axis.format;
    const tipDecimals = Math.max(axis.decimals, 2);
    tooltipFormatter = (v) => `${v.toFixed(tipDecimals)} ETH`;
  } else {
    // USD: merge BTC×btcPrice + ETH×ethPrice, align by timestamp using BTC as base
    const ethMap = new Map(ethData.map((d) => [d.time, d.value]));
    chartData = btcData.map((d) => {
      const ethVal = ethMap.get(d.time) ?? 0;
      return [d.time, d.value * btcPrice + ethVal * ethPrice];
    });
    seriesValues = chartData.map((p) => p[1]);
    const axis = pickAxisFormatter(seriesValues, USD_PRESET);
    yFormatter = axis.format;
    tooltipFormatter = (v) => {
      if (!Number.isFinite(v)) return '';
      const opts: Intl.NumberFormatOptions =
        Math.abs(v) < 100
          ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
          : { maximumFractionDigits: 0 };
      return `$${v.toLocaleString(undefined, opts)}`;
    };
  }

  const lineColor = unit === 'ETH' ? CHART.ethBlue : CHART.accent;
  const flatInfo = isEquityFlat(seriesValues, unit);
  const isFlat = flatInfo.flat;

  const option = {
    grid: { top: 20, right: 20, bottom: 30, left: 70 },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: CHART.divider } },
      axisLabel: { fontSize: 10, color: CHART.secondary },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { fontSize: 10, color: CHART.secondary, formatter: yFormatter },
      splitLine: isFlat ? { show: false } : { lineStyle: { color: '#F0EDE6' } },
      scale: !isFlat,
      min: isFlat ? flatInfo.level - Math.max(flatInfo.threshold, 1e-9) * 5 : undefined,
      max: isFlat ? flatInfo.level + Math.max(flatInfo.threshold, 1e-9) * 5 : undefined,
    },
    series: [
      {
        type: 'line',
        data: chartData,
        showSymbol: false,
        lineStyle: { color: lineColor, width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: unit === 'ETH' ? CHART_RGBA.ethBlue(0.15) : CHART_RGBA.accent(0.15) },
              { offset: 1, color: unit === 'ETH' ? CHART_RGBA.ethBlue(0.01) : CHART_RGBA.accent(0.01) },
            ],
          },
        },
        smooth: true,
      },
    ],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: CHART.divider,
      textStyle: { fontSize: 11, color: CHART.primary },
      formatter: (params: any) => {
        const p = params[0];
        if (!p) return '';
        const date = new Date(p.data[0]).toLocaleString();
        return `${date}<br/><b>${tooltipFormatter(p.data[1])}</b>`;
      },
    },
  };

  const hasData = unit === 'ETH' ? ethData.length > 0 : btcData.length > 0;

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-y-2 mb-3">
        <div className="flex gap-1 bg-cream rounded-lg p-1">
          {(['BTC', 'ETH', 'USD'] as Unit[]).map((u) => (
            <button
              key={u}
              onClick={() => setUnit(u)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                unit === u ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              {u}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-cream rounded-lg p-1">
          {TIME_RANGES.map((r, i) => (
            <button
              key={r}
              onClick={() => setActiveRange(i)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                i === activeRange ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      {loading || !hasData ? (
        <div className="flex items-center justify-center h-[200px] text-secondary text-sm">
          {loading ? <div className="space-y-2 w-full"><div className="h-[200px] bg-cream rounded animate-pulse" /></div> : 'No equity data yet'}
        </div>
      ) : (
        <div className="relative">
          <ReactECharts option={option} style={{ height: 200 }} notMerge />
          {isFlat && (
            <span className="absolute top-2 right-3 text-[10px] text-secondary font-mono bg-cream/90 rounded px-1.5 py-0.5 border border-divider">
              &asymp; flat
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default EquityCurve;
