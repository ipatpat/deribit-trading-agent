import { useState, useCallback } from 'react';
import * as Slider from '@radix-ui/react-slider';
import Panel from '../components/common/Panel';
import TradingViewWidget from '../components/charts/TradingViewWidget';
import OrderBook from '../components/trading/OrderBook';
import SmartOrderBar from '../components/trading/SmartOrderBar';
import { createSmartOrder, placeOrder } from '../api/client';
import { useSmartOrdersStore } from '../stores/smartOrders';
import { formatUsd } from '../utils/format';
import { useToastStore } from '../stores/toast';

const INSTRUMENTS = ['BTC-PERPETUAL', 'ETH-PERPETUAL'] as const;

type OrderMode = 'smart' | 'limit' | 'market';

function EmbeddedOrderForm({
  instrument,
  direction,
}: {
  instrument: string;
  direction: 'buy' | 'sell';
}) {
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState<OrderMode>('smart');
  const [patience, setPatience] = useState([0.5]);
  const [price, setPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addOrder = useSmartOrdersStore((s) => s.addOrder);
  const showToast = useToastStore((s) => s.show);
  const amountNum = parseFloat(amount) || 0;
  const makerFee = amountNum * 0.0001;
  const takerFee = amountNum * 0.0005;
  const feeSaved = takerFee - makerFee;

  const handleSubmit = useCallback(async () => {
    if (amountNum <= 0) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'smart') {
        const order = await createSmartOrder({
          instrument_name: instrument,
          direction,
          amount: amountNum,
          patience: patience[0],
        });
        addOrder(order);
      } else {
        await placeOrder({
          instrument_name: instrument,
          direction,
          amount: amountNum,
          order_type: mode,
          price: mode === 'limit' ? parseFloat(price) : undefined,
        });
      }
      showToast('success', 'Order placed successfully');
      setAmount('');
      setPrice('');
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      showToast('error', msg);
    } finally {
      setSubmitting(false);
    }
  }, [amountNum, mode, instrument, direction, patience, price, addOrder, showToast]);

  return (
    <div className="space-y-4 pt-2">
      <div className="flex gap-1 bg-cream rounded-full p-1 w-full">
        {(['smart', 'limit', 'market'] as OrderMode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${
              mode === m
                ? 'bg-white text-primary shadow-sm'
                : 'bg-transparent text-secondary hover:text-primary'
            }`}
          >
            {m === 'smart' ? 'Smart' : m === 'limit' ? 'Limit' : 'Market'}
          </button>
        ))}
      </div>

      <input
        type="number"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        placeholder="Amount (USD)"
        className="w-full px-4 py-2 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-secondary transition-colors"
      />

      {mode === 'limit' && (
        <input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="Limit price"
          className="w-full px-4 py-2 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-secondary transition-colors"
        />
      )}

      {mode === 'smart' && (
        <div className="pt-2">
          <Slider.Root
            value={patience}
            onValueChange={setPatience}
            min={0} max={1} step={0.01}
            className="relative flex items-center select-none touch-none w-full h-5"
          >
            <Slider.Track className="bg-cream-dark relative grow rounded-full h-1.5">
              <Slider.Range className="absolute bg-secondary rounded-full h-full" />
            </Slider.Track>
            <Slider.Thumb className="block w-4 h-4 bg-white border-2 border-secondary rounded-full shadow-sm focus:outline-none" />
          </Slider.Root>
          <div className="flex justify-between mt-2 text-[10px] text-secondary uppercase tracking-widest font-semibold">
            <span>Fast</span>
            <span>Patient</span>
          </div>
        </div>
      )}

      {amountNum > 0 && (
        <div className="flex justify-between text-xs text-secondary uppercase tracking-wider mt-2 border-t border-divider pt-3">
          <span>Save: <span className="text-profit font-mono font-medium">{formatUsd(feeSaved)}</span></span>
          <span>Maker: <span className="font-mono font-medium">{formatUsd(makerFee)}</span></span>
        </div>
      )}

      {error && <div className="text-xs text-loss font-medium mt-1">{error}</div>}

      <button
        onClick={handleSubmit}
        disabled={submitting || amountNum <= 0}
        className={`w-full py-3 rounded-lg text-sm font-bold tracking-wide transition-all disabled:opacity-50 shadow-sm mt-2 ${
          direction === 'buy'
            ? 'bg-profit text-white hover:bg-profit/90'
            : 'bg-loss text-white hover:bg-loss/90'
        }`}
      >
        {submitting ? 'Submitting...' : mode === 'smart' ? `Smart ${direction}` : `${direction} ${instrument.split('-')[0]}`}
      </button>
    </div>
  );
}

function Futures() {
  const [instrument, setInstrument] = useState<string>(INSTRUMENTS[0]);
  const [orderDirection, setOrderDirection] = useState<'buy' | 'sell'>('buy');

  return (
    <div className="trading-mode flex flex-col h-[calc(100vh-var(--topbar-height))] overflow-hidden bg-cream">
      {/* Top Toolbar */}
      <div className="bg-white px-6 py-3 flex items-center gap-6 flex-shrink-0 z-10 border-b border-divider-strong rounded-lg">
        <div className="flex gap-1">
          {INSTRUMENTS.map((inst) => (
            <button
              key={inst}
              onClick={() => setInstrument(inst)}
              className={`px-4 py-1.5 rounded-full text-sm font-bold transition-colors ${
                instrument === inst
                  ? 'bg-primary text-white'
                  : 'text-secondary hover:text-primary hover:bg-cream'
              }`}
            >
              {inst.replace('-PERPETUAL', '')}
            </button>
          ))}
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex flex-1 min-h-0 overflow-y-auto px-6 py-6 pb-24">
        <div className="flex-1 flex max-w-content mx-auto w-full gap-8">
          
          {/* Left: TradingView Chart */}
          <div className="flex-1 flex flex-col min-w-0">
            <Panel className="h-full flex flex-col"
              header={<span className="text-lg font-semibold text-primary">Chart</span>}
              contentClassName="p-1 flex-1 min-h-0"
            >
              <div className="h-full min-h-[500px] overflow-hidden">
                <TradingViewWidget
                  symbol={instrument === 'ETH-PERPETUAL' ? 'DERIBIT:ETHUSD.P' : 'DERIBIT:BTCUSD.P'}
                  height="100%"
                />
              </div>
            </Panel>
          </div>

          {/* Right: OrderBook + Order Form */}
          <div className="w-[360px] flex-shrink-0 flex flex-col gap-6">
            
            {/* Order Book */}
            <Panel
              header={<span className="text-lg font-semibold text-primary">Order Book</span>}
              contentClassName="p-4"
            >
              <OrderBook instrument={instrument} depth={12} />
            </Panel>

            {/* Order Form */}
            <Panel
              header={<span className="text-lg font-semibold text-primary">Place Order</span>}
              contentClassName="p-5"
            >
              <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => setOrderDirection('buy')}
                    className={`flex-1 py-2 rounded-lg text-sm font-bold tracking-wide transition-colors ${
                      orderDirection === 'buy'
                        ? 'bg-profit-bg text-profit border border-profit/20'
                        : 'bg-transparent text-secondary hover:text-primary border border-transparent'
                    }`}
                  >
                    Buy
                  </button>
                  <button
                    onClick={() => setOrderDirection('sell')}
                    className={`flex-1 py-2 rounded-lg text-sm font-bold tracking-wide transition-colors ${
                      orderDirection === 'sell'
                        ? 'bg-loss-bg text-loss border border-loss/20'
                        : 'bg-transparent text-secondary hover:text-primary border border-transparent'
                    }`}
                  >
                    Sell
                  </button>
                </div>

                <EmbeddedOrderForm instrument={instrument} direction={orderDirection} />
            </Panel>

          </div>
        </div>
      </div>

      <SmartOrderBar />
    </div>
  );
}

export default Futures;
