/** Maps to the backend Pydantic Ticker model */
export interface Ticker {
  instrument_name: string;
  mark_price: number;
  index_price: number;
  best_bid_price: number;
  best_ask_price: number;
  best_bid_amount: number;
  best_ask_amount: number;
  last_price: number;
  open_interest: number;
  volume_24h: number;
  price_change_24h: number;
  funding_rate?: number;
  estimated_delivery_price?: number;
  timestamp: number;
}

/** Maps to the backend Pydantic Position model */
export interface Position {
  instrument_name: string;
  direction: 'buy' | 'sell';
  size: number;
  average_price: number;
  mark_price: number;
  index_price: number;
  floating_profit_loss: number;
  realized_profit_loss: number;
  total_profit_loss: number;
  delta: number;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  leverage?: number;
  kind: 'future' | 'option';
}

/** Maps to the backend Pydantic Order model */
export interface Order {
  order_id: string;
  instrument_name: string;
  direction: 'buy' | 'sell';
  price: number;
  amount: number;
  filled_amount: number;
  order_type: 'limit' | 'market' | 'stop_limit' | 'stop_market';
  order_state: 'open' | 'filled' | 'cancelled' | 'rejected';
  label?: string;
  creation_timestamp: number;
  last_update_timestamp: number;
}

/** Maps to the backend Pydantic AccountSummary model */
export interface AccountSummary {
  currency: string;
  equity: number;
  balance: number;
  available_funds: number;
  margin_balance: number;
  initial_margin: number;
  maintenance_margin: number;
  delta_total: number;
  options_pl: number;
  futures_pl: number;
  session_upl: number;
  session_rpl: number;
}

export type SmartOrderState =
  | 'pending'
  | 'active'
  | 'escalating'
  | 'paused'
  | 'completed'
  | 'cancelled'
  | 'market_filled'
  | 'failed';

export type SmartOrderIntent = 'standard' | 'urgent';

/** Maps to the backend SmartOrder.to_dict() */
export interface SmartOrder {
  id: string;
  instrument: string;
  direction: 'buy' | 'sell';
  amount: number;
  intent: SmartOrderIntent | null;
  algorithm: string;
  state: SmartOrderState;
  deribit_order_id: string | null;
  current_price: number | null;
  current_level: number;
  filled_amount: number;
  amend_count: number;
  post_only_reject_count: number;
  elapsed_ms: number;
  t_patience_ms: number | null;
  fee_mode: string | null;
}

/** Maps to the backend Pydantic Greeks model */
export interface Greeks {
  delta: number;
  gamma: number;
  vega: number;
  theta: number;
  rho: number;
}

/** Maps to the backend Pydantic PortfolioSnapshot model */
export interface PortfolioSnapshot {
  equity: number;
  balance: number;
  unrealized_pnl: number;
  realized_pnl: number;
  positions: Position[];
  greeks_summary: {
    net_delta: number;
    net_gamma: number;
    net_theta: number;
    net_vega: number;
  };
  currency: string;
  timestamp: number;
}

/** Maps to the backend Pydantic EquityCurvePoint model */
export interface EquityCurvePoint {
  timestamp: number;
  equity: number;
  balance: number;
}

/** Option chain row as returned by the API */
export interface OptionChainRow {
  strike: number;
  call: Ticker | null;
  put: Ticker | null;
}

/** Vol surface data point */
export interface VolSurfacePoint {
  strike: number;
  expiry: string;
  iv: number;
}

/** OHLCV candle */
export interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** WebSocket message envelope */
export interface WsMessage<T = unknown> {
  type: 'ticker' | 'portfolio' | 'order' | 'trade' | 'smart_order';
  data: T;
}
