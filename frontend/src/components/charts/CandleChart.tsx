import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { getCandles } from '../../api/client';
import type { Candle } from '../../types/api';
import { usePolling } from '../../utils/usePolling';
import { useRefreshInterval } from '../../stores/settings';
import { CHART, CHART_RGBA } from '../../utils/chartColors';

const RESOLUTIONS = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '1h', value: '1h' },
  { label: '1d', value: '1d' },
] as const;

interface CandleChartProps {
  instrument: string;
}

function CandleChart({ instrument }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [activeRes, setActiveRes] = useState(2); // default 1h
  const [loading, setLoading] = useState(true);
  const activeResRef = useRef(2);
  const refreshMs = useRefreshInterval('candles');

  const fetchData = useCallback(
    async (resolution: string) => {
      setLoading(true);
      try {
        const periodMs: Record<string, number> = {
          '1m': 3_600_000,
          '5m': 14_400_000,
          '1h': 86_400_000,
          '1d': 604_800_000,
        };
        const now = Date.now();
        const since = now - (periodMs[resolution] || 86_400_000);
        const data = await getCandles(instrument, resolution, since, now);
        if (candleSeriesRef.current && volumeSeriesRef.current) {
          const candles = data.map((c: Candle) => ({
            time: (c.timestamp / 1000) as number,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }));
          const volumes = data.map((c: Candle) => ({
            time: (c.timestamp / 1000) as number,
            value: c.volume,
            color: c.close >= c.open ? CHART_RGBA.profit(0.3) : CHART_RGBA.loss(0.3),
          }));
          candleSeriesRef.current.setData(candles as any);
          volumeSeriesRef.current.setData(volumes as any);
          chartRef.current?.timeScale().fitContent();
        }
      } catch {
        // silently handle
      } finally {
        setLoading(false);
      }
    },
    [instrument],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#FFFFFF' },
        textColor: CHART.secondary,
        fontFamily: '"SF Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
      },
      grid: {
        vertLines: { color: '#F0EDE6' },
        horzLines: { color: '#F0EDE6' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: CHART.divider },
      timeScale: { borderColor: CHART.divider },
      width: containerRef.current.clientWidth,
      height: 500,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: CHART.profit,
      downColor: CHART.loss,
      borderUpColor: CHART.profit,
      borderDownColor: CHART.loss,
      wickUpColor: CHART.profit,
      wickDownColor: CHART.loss,
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        chart.applyOptions({ width });
      }
    });
    ro.observe(containerRef.current);

    fetchData(RESOLUTIONS[activeRes].value);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument]);

  // Silent periodic refresh (no loading spinner)
  const silentRefetch = useCallback(async () => {
    const resolution = RESOLUTIONS[activeResRef.current].value;
    try {
      const periodMs: Record<string, number> = {
        '1m': 3_600_000,
        '5m': 14_400_000,
        '1h': 86_400_000,
        '1d': 604_800_000,
      };
      const now = Date.now();
      const since = now - (periodMs[resolution] || 86_400_000);
      const data = await getCandles(instrument, resolution, since, now);
      if (candleSeriesRef.current && volumeSeriesRef.current) {
        const candles = data.map((c: Candle) => ({
          time: (c.timestamp / 1000) as number,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }));
        const volumes = data.map((c: Candle) => ({
          time: (c.timestamp / 1000) as number,
          value: c.volume,
          color: c.close >= c.open ? 'rgba(4, 149, 84, 0.3)' : 'rgba(255, 59, 48, 0.3)',
        }));
        candleSeriesRef.current.setData(candles as any);
        volumeSeriesRef.current.setData(volumes as any);
      }
    } catch {
      // silently handle
    }
  }, [instrument]);

  usePolling(() => {
    silentRefetch();
  }, refreshMs);

  const handleResolution = (index: number) => {
    setActiveRes(index);
    activeResRef.current = index;
    fetchData(RESOLUTIONS[index].value);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-primary">{instrument}</h3>
        <div className="flex gap-1 bg-cream rounded-lg p-1">
          {RESOLUTIONS.map((r, i) => (
            <button
              key={r.label}
              onClick={() => handleResolution(i)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                i === activeRes
                  ? 'bg-primary text-white'
                  : 'text-secondary hover:text-primary'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {loading && (
        <div className="h-[500px] bg-cream rounded animate-pulse" />
      )}
      <div ref={containerRef} className={loading ? 'opacity-0 h-0' : ''} />
    </div>
  );
}

export default CandleChart;
