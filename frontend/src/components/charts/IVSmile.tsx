import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { CHART } from '../../utils/chartColors';
import { pickAxisFormatter, IV_PRESET } from '../../utils/axisFormat';

interface IVSmileProps {
  data: { strike: number; iv: number }[];
  atmStrike?: number;
}

function IVSmile({ data, atmStrike }: IVSmileProps) {
  const ivValues = data.map((d) => d.iv).filter((v) => Number.isFinite(v));
  const ivAxis = pickAxisFormatter(ivValues, IV_PRESET);

  const option: EChartsOption = {
    grid: { top: 30, right: 20, bottom: 40, left: 50 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.strike),
      name: 'Strike Price',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { fontSize: 10, color: CHART.secondary },
      axisLine: { lineStyle: { color: CHART.divider } },
    },
    yAxis: {
      type: 'value',
      name: 'IV %',
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
        data: data.map((d) => d.iv),
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: CHART.accent, width: 2 },
        itemStyle: { color: CHART.accent },
        markLine: atmStrike
          ? {
              silent: true,
              symbol: 'none',
              lineStyle: { color: CHART.primary, type: 'dashed', width: 1 },
              data: [{ xAxis: atmStrike, label: { formatter: 'ATM', fontSize: 10 } }],
            }
          : undefined,
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        return `Strike: ${p.name}<br/>IV: ${Number(p.value).toFixed(2)}%`;
      },
    },
  };

  return <ReactECharts option={option} style={{ height: 250 }} notMerge />;
}

export default IVSmile;
