import { useState, useCallback } from 'react';
import * as Slider from '@radix-ui/react-slider';
import { X } from 'lucide-react';
import { createSmartOrder, placeOrder } from '../../api/client';
import { useSmartOrdersStore } from '../../stores/smartOrders';
import { useToastStore } from '../../stores/toast';
import { formatUsd } from '../../utils/format';

type Direction = 'buy' | 'sell';
type OrderMode = 'smart' | 'limit' | 'market';

export interface OrderParams {
  instrument: string;
  direction: 'buy' | 'sell';
  amount: number;
  orderType: 'smart' | 'limit' | 'market';
  price?: number;
  patience?: number;
}

export interface OrderResult {
  success: boolean;
  order_id?: string;
  error?: string;
}

interface OptionContext {
  strike: number;
  expiry: string;
  type: 'C' | 'P';
}

interface OrderPanelProps {
  instrument?: string;
  direction?: Direction;
  optionContext?: OptionContext;
  orderStrategy?: (params: OrderParams) => Promise<OrderResult>;
  onClose: () => void;
  open: boolean;
}

function OrderPanel({
  instrument = 'BTC-PERPETUAL',
  direction: initialDirection,
  optionContext,
  orderStrategy,
  onClose,
  open,
}: OrderPanelProps) {
  const [dir, setDir] = useState<Direction>(initialDirection ?? 'buy');
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState<OrderMode>('smart');
  const [patience, setPatience] = useState([0.5]);
  const [price, setPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const addOrder = useSmartOrdersStore((s) => s.addOrder);
  const showToast = useToastStore((s) => s.show);

  const amountNum = parseFloat(amount) || 0;
  const makerFee = amountNum * 0.0001;
  const takerFee = amountNum * 0.0005;
  const feeSaved = takerFee - makerFee;

  const orderTypeLabel = mode === 'smart' ? 'Smart Order' : mode === 'limit' ? 'Limit' : 'Market';

  const handleSubmit = useCallback(async () => {
    if (!amount || amountNum <= 0) return;
    setSubmitting(true);
    setError(null);
    setShowConfirm(false);

    const params: OrderParams = {
      instrument,
      direction: dir,
      amount: amountNum,
      orderType: mode,
      price: mode === 'limit' ? parseFloat(price) : undefined,
      patience: mode === 'smart' ? patience[0] : undefined,
    };

    try {
      if (orderStrategy) {
        const result = await orderStrategy(params);
        if (!result.success) throw new Error(result.error ?? 'Order failed');
      } else if (mode === 'smart') {
        const order = await createSmartOrder({
          instrument_name: instrument,
          direction: dir,
          amount: amountNum,
          patience: patience[0],
        });
        addOrder(order);
      } else {
        await placeOrder({
          instrument_name: instrument,
          direction: dir,
          amount: amountNum,
          order_type: mode,
          price: mode === 'limit' ? parseFloat(price) : undefined,
        });
      }
      showToast('success', 'Order placed successfully');
      setAmount('');
      setPrice('');
      onClose();
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      showToast('error', msg);
    } finally {
      setSubmitting(false);
    }
  }, [amount, amountNum, mode, instrument, dir, patience, price, addOrder, onClose, orderStrategy, showToast]);

  const submitLabel = submitting
    ? 'Submitting...'
    : mode === 'smart'
      ? 'Create Smart Order'
      : 'Place Order';

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      )}

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 bottom-0 w-panel bg-white shadow-popup z-50 flex flex-col transition-transform duration-300 ease-in-out ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-divider">
          <div>
            <h2 className="text-lg font-semibold text-primary">{instrument}</h2>
            {optionContext && (
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${optionContext.type === 'C' ? 'bg-profit-bg text-profit' : 'bg-loss-bg text-loss'}`}>
                  {optionContext.type === 'C' ? 'Call' : 'Put'}
                </span>
                <span className="text-xs text-secondary">Strike {optionContext.strike.toLocaleString()}</span>
                <span className="text-xs text-secondary">{optionContext.expiry}</span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-secondary hover:text-primary transition-colors"
            aria-label="Close order panel"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Direction toggle */}
          <div className="flex gap-1">
            <button
              onClick={() => setDir('buy')}
              className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-colors ${
                dir === 'buy'
                  ? 'bg-profit text-white'
                  : 'bg-cream text-secondary hover:text-primary'
              }`}
            >
              Buy
            </button>
            <button
              onClick={() => setDir('sell')}
              className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-colors ${
                dir === 'sell'
                  ? 'bg-loss text-white'
                  : 'bg-cream text-secondary hover:text-primary'
              }`}
            >
              Sell
            </button>
          </div>

          {/* Amount */}
          <div>
            <label className="block text-xs text-secondary font-medium uppercase tracking-wider mb-1.5">
              Amount
            </label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full px-3 py-2 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
            />
          </div>

          {/* Order mode tabs */}
          <div className="flex gap-1 bg-cream rounded-lg p-1">
            {(['smart', 'limit', 'market'] as OrderMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  mode === m
                    ? 'bg-primary text-white'
                    : 'text-secondary hover:text-primary'
                }`}
              >
                {m === 'smart' ? 'Smart Order' : m === 'limit' ? 'Limit' : 'Market'}
              </button>
            ))}
          </div>

          {/* Limit price input */}
          {mode === 'limit' && (
            <div>
              <label className="block text-xs text-secondary font-medium uppercase tracking-wider mb-1.5">
                Limit Price
              </label>
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="0.00"
                className="w-full px-3 py-2 border border-divider rounded-lg font-mono text-primary text-sm focus:outline-none focus:border-accent transition-colors"
              />
            </div>
          )}

          {/* Smart Order: patience slider */}
          {mode === 'smart' && (
            <div>
              <label className="block text-xs text-secondary font-medium uppercase tracking-wider mb-3">
                Patience
              </label>
              <Slider.Root
                value={patience}
                onValueChange={setPatience}
                min={0}
                max={1}
                step={0.01}
                className="relative flex items-center select-none touch-none w-full h-5"
              >
                <Slider.Track className="bg-cream-dark relative grow rounded-full h-1.5">
                  <Slider.Range className="absolute bg-accent rounded-full h-full" />
                </Slider.Track>
                <Slider.Thumb className="block w-4 h-4 bg-white border-2 border-accent rounded-full focus:outline-none focus:ring-2 focus:ring-accent/30" />
              </Slider.Root>
              <div className="flex justify-between mt-1.5 text-xs text-secondary">
                <span>Aggressive</span>
                <span className="font-mono">{patience[0].toFixed(2)}</span>
                <span>Patient</span>
              </div>
            </div>
          )}

          {/* Fee estimate */}
          {amountNum > 0 && (
            <div className="bg-cream rounded-lg p-4 space-y-2">
              <div className="text-xs text-secondary font-medium uppercase tracking-wider mb-2">
                Fee Estimate
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-secondary">Maker</span>
                <span className="font-mono text-primary">{formatUsd(makerFee)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-secondary">Taker</span>
                <span className="font-mono text-primary">{formatUsd(takerFee)}</span>
              </div>
              <div className="flex justify-between text-sm border-t border-divider pt-2">
                <span className="text-secondary">Save</span>
                <span className="font-mono text-profit">{formatUsd(feeSaved)}</span>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="text-sm text-loss bg-loss-bg rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* Submit */}
        <div className="px-6 py-4 border-t border-divider">
          <button
            onClick={() => setShowConfirm(true)}
            disabled={!amount || amountNum <= 0}
            className={`w-full py-2.5 rounded-lg text-white text-sm font-semibold transition-all disabled:opacity-40 ${
              dir === 'buy'
                ? 'bg-profit hover:bg-profit/90'
                : 'bg-loss hover:bg-loss/90'
            }`}
          >
            {submitLabel}
          </button>
        </div>
      </div>

      {/* Confirmation Modal */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center" onClick={() => setShowConfirm(false)}>
          <div className="bg-white rounded-card shadow-popup p-6 w-[360px] max-w-[90vw]" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-primary mb-4">Confirm Order</h3>

            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-secondary">Instrument</span>
                <span className="font-mono text-primary font-medium">{instrument}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-secondary">Direction</span>
                <span className={`font-semibold ${dir === 'buy' ? 'text-profit' : 'text-loss'}`}>
                  {dir === 'buy' ? 'Buy' : 'Sell'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-secondary">Amount</span>
                <span className="font-mono text-primary">{amountNum}</span>
              </div>
              {mode === 'limit' && price && (
                <div className="flex justify-between">
                  <span className="text-secondary">Price</span>
                  <span className="font-mono text-primary">{parseFloat(price).toFixed(2)}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-secondary">Type</span>
                <span className="text-primary">{orderTypeLabel}</span>
              </div>
              {amountNum > 0 && (
                <div className="flex justify-between">
                  <span className="text-secondary">Est. Fee</span>
                  <span className="font-mono text-primary">{formatUsd(makerFee)} ~ {formatUsd(takerFee)}</span>
                </div>
              )}
            </div>

            <div className="flex gap-2 mt-6">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 py-2.5 rounded-lg border border-divider text-secondary text-sm font-semibold hover:bg-cream transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className={`flex-1 py-2.5 rounded-lg text-white text-sm font-semibold transition-all disabled:opacity-40 ${
                  dir === 'buy' ? 'bg-profit hover:bg-profit/90' : 'bg-loss hover:bg-loss/90'
                }`}
              >
                {submitting ? 'Submitting...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default OrderPanel;
