import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { calculatePayoff, type OptionLeg } from '../../utils/payoff';
import { CHART, CHART_RGBA } from '../../utils/chartColors';

interface PayoffDiagramProps {
  legs: OptionLeg[];
}

function PayoffDiagram({ legs }: PayoffDiagramProps) {
  const points = calculatePayoff(legs);

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-[250px] text-secondary text-sm">
        Select options to see payoff diagram
      </div>
    );
  }

  const prices = points.map((p) => p.price);
  const pnls = points.map((p) => p.pnl);

  // Find breakeven points (where PnL crosses zero)
  const breakevenPrices: number[] = [];
  for (let i = 1; i < points.length; i++) {
    if (
      (points[i - 1].pnl <= 0 && points[i].pnl >= 0) ||
      (points[i - 1].pnl >= 0 && points[i].pnl <= 0)
    ) {
      // Linear interpolation
      const ratio = Math.abs(points[i - 1].pnl) / (Math.abs(points[i - 1].pnl) + Math.abs(points[i].pnl));
      const bep = points[i - 1].price + ratio * (points[i].price - points[i - 1].price);
      breakevenPrices.push(Math.round(bep * 100) / 100);
    }
  }

  const minPnl = Math.min(...pnls);
  const maxLossIdx = pnls.indexOf(minPnl);

  const profitData = pnls.map((v) => (v >= 0 ? v : 0));
  const lossData = pnls.map((v) => (v < 0 ? v : 0));

  const markLines: any[] = breakevenPrices.map((bep) => ({
    xAxis: bep,
    label: { formatter: `BE: ${bep}`, fontSize: 10, position: 'start' },
    lineStyle: { color: CHART.primary, type: 'dashed', width: 1 },
  }));

  const option: EChartsOption = {
    grid: { top: 40, right: 20, bottom: 40, left: 60 },
    xAxis: {
      type: 'category',
      data: prices,
      name: 'Price at Expiry',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: {
        fontSize: 10,
        color: CHART.secondary,
        interval: Math.floor(prices.length / 6),
      },
      axisLine: { lineStyle: { color: CHART.divider } },
    },
    yAxis: {
      type: 'value',
      name: 'P&L',
      nameLocation: 'middle',
      nameGap: 50,
      axisLabel: { fontSize: 10, color: CHART.secondary },
      splitLine: { lineStyle: { color: '#F0EDE6' } },
    },
    series: [
      {
        type: 'line',
        data: profitData,
        stack: 'pnl',
        areaStyle: { color: CHART_RGBA.profit(0.2) },
        lineStyle: { color: CHART.profit, width: 2 },
        itemStyle: { color: CHART.profit },
        symbol: 'none',
        markLine:
          markLines.length > 0
            ? { silent: true, symbol: 'none', data: markLines }
            : undefined,
      },
      {
        type: 'line',
        data: lossData,
        stack: 'pnl2',
        areaStyle: { color: CHART_RGBA.loss(0.2) },
        lineStyle: { color: CHART.loss, width: 2 },
        itemStyle: { color: CHART.loss },
        symbol: 'none',
        markPoint:
          minPnl < 0
            ? {
                data: [
                  {
                    name: 'Max Loss',
                    coord: [maxLossIdx, minPnl],
                    value: `Max Loss: ${minPnl.toFixed(2)}`,
                    symbol: 'pin',
                    symbolSize: 40,
                    itemStyle: { color: CHART.loss },
                    label: { fontSize: 9, color: '#fff' },
                  },
                ],
              }
            : undefined,
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        const idx = p.dataIndex;
        return `Price: ${prices[idx]}<br/>P&L: ${pnls[idx].toFixed(2)}`;
      },
    },
  };

  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}

export default PayoffDiagram;
