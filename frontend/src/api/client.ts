import type {
  EquityCurvePoint,
  Position,
  PortfolioSnapshot,
  Candle,
  SmartOrder,
  Order,
} from '../types/api';

const BASE = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

/* ── Portfolio / Account ── */

export function getEquityCurve(period = '1d', currency = 'BTC'): Promise<Record<string, unknown>> {
  const periodMs: Record<string, number> = {
    '1h': 3_600_000,
    '1d': 86_400_000,
    '7d': 604_800_000,
    '30d': 2_592_000_000,
  };
  const now = Date.now();
  const since = now - (periodMs[period] || 86_400_000);
  return request(`/equity-curve?currency=${currency}&since=${since}&until=${now}`);
}

export function getPositions(currency = 'BTC'): Promise<Position[]> {
  return request(`/positions?currency=${currency}`);
}

export function getPortfolioSnapshot(currency = 'BTC'): Promise<PortfolioSnapshot> {
  return request(`/portfolio/snapshot?currency=${currency}`);
}

export interface PortfolioOverview {
  accounts: Record<string, any>;
  positions: Position[];
  index_prices: Record<string, number>;
  total_usd: number;
}

export function getPortfolioOverview(): Promise<PortfolioOverview> {
  return request('/portfolio/overview');
}

/* ── Options ── */

export function getOptionChain(currency: string, expiry?: string): Promise<Record<string, unknown>> {
  const params = new URLSearchParams({ currency });
  if (expiry) params.set('expiry', expiry);
  return request(`/options/chain?${params}`);
}

export function getExpiries(currency: string): Promise<{ timestamp: number; expiry: string }[]> {
  return request(`/options/expiries?currency=${currency}`);
}

export function getVolSurface(currency: string): Promise<Record<string, unknown>> {
  return request(`/options/vol-surface?currency=${currency}`);
}

/* ── Market Data ── */

export function getCandles(
  instrument = 'BTC-PERPETUAL',
  resolution = '1m',
  since?: number,
  until?: number,
): Promise<Candle[]> {
  const now = Date.now();
  const s = since || now - 3_600_000;
  const u = until || now;
  return request(`/candles?instrument=${instrument}&resolution=${resolution}&since=${s}&until=${u}`);
}

/* ── Risk ── */

export function getRiskStatus(): Promise<Record<string, unknown>> {
  return request('/risk/status');
}

export function updateRiskConfig(config: Record<string, number>): Promise<Record<string, unknown>> {
  return request('/risk/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

export function resumeTrading(): Promise<Record<string, unknown>> {
  return request('/risk/resume', { method: 'POST' });
}

/* ── Smart Orders ── */

export function getSmartOrders(activeOnly = true): Promise<SmartOrder[]> {
  return request(`/smart-orders?active_only=${activeOnly}`);
}

export interface SmartOrderOverrides {
  t_patience_ms?: number;
  max_cross_levels?: number;
  price_limit_pct?: number;
  price_limit_ticks?: number;
  price_limit_iv?: number;
  prefer_maker?: boolean;
}

export function createSmartOrder(params: {
  instrument_name: string;
  direction: string;
  amount: number;
  intent?: 'standard' | 'urgent';
  overrides?: SmartOrderOverrides;
}): Promise<SmartOrder> {
  return request('/smart-orders', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export function cancelSmartOrder(id: string): Promise<SmartOrder> {
  return request(`/smart-orders/${id}`, { method: 'DELETE' });
}

export function smartOrderAction(id: string, action: string): Promise<SmartOrder> {
  return request(`/smart-orders/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

/* ── Trading ── */

export function placeOrder(params: {
  instrument_name: string;
  direction: 'buy' | 'sell';
  amount: number;
  order_type: string;
  price?: number;
  label?: string;
}): Promise<Order> {
  return request('/orders', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

/* ── Health ── */

export function getHealth(): Promise<Record<string, unknown>> {
  return request('/health');
}

/* ── Settings ── */

export function getSettingsStatus(): Promise<{
  env: string;
  ws_url: string;
  connected: boolean;
  authenticated: boolean;
  client_id: string;
  is_production: boolean;
  allow_live_trading: boolean;
  uptime_ms: number;
  client_id_tail: string;
  has_credentials: boolean;
  production_endpoint: string;
}> {
  return request('/settings/status');
}

export function saveCredentials(params: {
  client_id: string;
  client_secret: string;
  env: string;
  endpoint?: string;
}): Promise<Record<string, unknown>> {
  return request('/settings/credentials', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export function switchEnv(env: string): Promise<Record<string, unknown>> {
  return request('/settings/switch-env', {
    method: 'POST',
    body: JSON.stringify({ env }),
  });
}

export function clearKeys(env: string): Promise<Record<string, unknown>> {
  return request('/settings/clear-keys', {
    method: 'POST',
    body: JSON.stringify({ env }),
  });
}

export function clearAccountData(env: string): Promise<Record<string, unknown>> {
  return request('/settings/clear-account-data', {
    method: 'POST',
    body: JSON.stringify({ env }),
  });
}

/* ── Payoff ── */

export interface PayoffLeg {
  instrument: string;
  direction: 'buy' | 'sell';
  amount: number;
}

export interface PayoffResult {
  legs: any[];
  payoff_btc: { price: number; pnl: number }[];
  payoff_usd: { price: number; pnl: number }[];
  underlying_price: number;
  summary: {
    max_profit_btc: number;
    max_loss_btc: number;
    max_profit_usd: number;
    max_loss_usd: number;
    breakeven: number[];
    net_premium_btc: number;
    net_delta: number;
    net_theta: number;
    risk_reward_ratio: number;
  };
}

export function calculatePayoff(legs: PayoffLeg[]): Promise<PayoffResult> {
  return request('/options/payoff', {
    method: 'POST',
    body: JSON.stringify({ legs }),
  });
}
