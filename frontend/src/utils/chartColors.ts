// Chart color constants — derived from tailwind.config.ts design tokens.
// Use these in ECharts options instead of hardcoded hex values.

export const CHART = {
  accent: '#F05C00',
  primary: '#1C1C1E',
  secondary: '#939191',
  divider: '#EBEBEB',  /* matches rgba(0,0,0,0.08) on white */
  profit: '#049554',
  loss: '#FF3B30',
  ethBlue: '#627EEA',
} as const;

export const CHART_RGBA = {
  accent: (alpha: number) => `rgba(240, 92, 0, ${alpha})`,
  profit: (alpha: number) => `rgba(4, 149, 84, ${alpha})`,
  loss: (alpha: number) => `rgba(255, 59, 48, ${alpha})`,
  ethBlue: (alpha: number) => `rgba(98, 126, 234, ${alpha})`,
} as const;
