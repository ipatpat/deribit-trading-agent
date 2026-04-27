import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { CHART } from '../../utils/chartColors';
import { pickAxisFormatter, IV_PRESET } from '../../utils/axisFormat';

interface TermStructureProps {
  data: { daysToExpiry: number; atmIv: number }[];
}

function TermStructure({ data }: TermStructureProps) {
  const sorted = [...data].sort((a, b) => a.daysToExpiry - b.daysToExpiry);
  const ivValues = sorted.map((d) => d.atmIv).filter((v) => Number.isFinite(v));
  const ivAxis = pickAxisFormatter(ivValues, IV_PRESET);

  const option: EChartsOption = {
    grid: { top: 30, right: 20, bottom: 40, left: 50 },
    xAxis: {
      type: 'category',
      data: sorted.map((d) => `${d.daysToExpiry}d`),
      name: 'Days to Expiry',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { fontSize: 10, color: CHART.secondary },
      axisLine: { lineStyle: { color: CHART.divider } },
    },
    yAxis: {
      type: 'value',
      name: 'ATM IV %',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: {
        fontSize: 10,
        color: CHART.secondary,
        formatter: ivAxis.format,
      },
      splitLine: { lineStyle: { color: '#F0EDE6' } },
    },
    series: [
      {
        type: 'line',
        data: sorted.map((d) => d.atmIv),
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: CHART.accent, width: 2 },
        itemStyle: { color: CHART.accent },
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        return `${p.name}<br/>ATM IV: ${Number(p.value).toFixed(2)}%`;
      },
    },
  };

  return <ReactECharts option={option} style={{ height: 250 }} notMerge />;
}

export default TermStructure;
