/**
 * Format a price with the given decimal precision.
 * Defaults to 2 decimals; crypto prices often need more.
 */
export function formatPrice(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '-';
  return value.toFixed(decimals);
}

/**
 * Format a number as USD: $1,234.56
 */
export function formatUsd(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format a number as a percentage string: 12.34%
 */
export function formatPercent(value: number, decimals = 2): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Format a number as compact USD: $1.2k, $3.5M, $999
 */
export function formatCompactUsd(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(2)}M`;
  }
  if (abs >= 1_000) {
    return `$${(value / 1_000).toFixed(1)}k`;
  }
  return `$${value.toFixed(abs < 1 ? 2 : 0)}`;
}

/**
 * Format a Unix-ms timestamp to a locale date-time string.
 */
export function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
