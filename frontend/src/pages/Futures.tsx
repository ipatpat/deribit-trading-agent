import { useState, useCallback, useMemo, useRef, useEffect, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, BookOpen, X } from 'lucide-react';
import Panel from '../components/common/Panel';
import TradingViewWidget from '../components/charts/TradingViewWidget';
import OrderBook from '../components/trading/OrderBook';
import SmartOrderBar from '../components/trading/SmartOrderBar';
import { createSmartOrder, placeOrder, type SmartOrderOverrides } from '../api/client';
import { useSmartOrdersStore } from '../stores/smartOrders';
import { useFuturesStore, FUTURES_INSTRUMENTS } from '../stores/futures';
import { useChatStore } from '../stores/chat';
import { useIsNarrowViewport } from '../hooks/useViewportWidth';
import { useToastStore } from '../stores/toast';

function FuturesInstrumentSelector() {
  const selected = useFuturesStore((s) => s.selectedInstrument);
  const setSelected = useFuturesStore((s) => s.setSelectedInstrument);
  return (
    <div className="flex gap-1">
      {FUTURES_INSTRUMENTS.map((inst) => {
        const active = selected === inst;
        return (
          <button
            key={inst}
            onClick={() => setSelected(inst)}
            className={`px-3 h-8 rounded-full text-sm font-bold transition-colors ${
              active
                ? 'bg-primary text-white'
                : 'text-secondary hover:text-primary hover:bg-cream'
            }`}
          >
            {inst.replace('-PERPETUAL', '')}
          </button>
        );
      })}
    </div>
  );
}
import {
  OVERRIDE_DISPLAY,
  isOptionInstrument,
  overridesToApi,
  validateOverrides,
  type UiOverrides,
} from '../utils/smartOrderValidation';


type OrderMode = 'smart' | 'limit' | 'market';
type Intent = 'standard' | 'urgent';

const INTENT_BLURB: Record<Intent, string> = {
  standard: 'Maker fill, escalates on patience',
  urgent: 'Take liquidity now (IOC then market)',
};

function NumberField({
  label,
  unit,
  tooltip,
  value,
  onChange,
  step,
  placeholder,
}: {
  label: string;
  unit?: string;
  tooltip?: string;
  value: string;
  onChange: (v: string) => void;
  step?: string;
  placeholder?: string;
}) {
  return (
    <label className="block" title={tooltip}>
      <span className="block text-[10px] text-secondary uppercase tracking-wider font-semibold mb-1">
        {label}
        {unit && <span className="ml-1 text-secondary/70 normal-case">({unit})</span>}
      </span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-1.5 border border-divider rounded-md font-mono text-primary text-xs focus:outline-none focus:border-secondary"
      />
    </label>
  );
}

function EmbeddedOrderForm({
  instrument,
  direction,
}: {
  instrument: string;
  direction: 'buy' | 'sell';
}) {
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState<OrderMode>('smart');
  const [intent, setIntent] = useState<Intent>('standard');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // UI-unit values: timeout in seconds, priceLimitPct as percentage (0.30 not 0.003)
  const [timeoutS, setTimeoutS] = useState('');
  const [maxIocLevels, setMaxIocLevels] = useState('');
  const [priceLimitPctUi, setPriceLimitPctUi] = useState('');
  const [priceLimitTicks, setPriceLimitTicks] = useState('');
  const [priceLimitIv, setPriceLimitIv] = useState('');
  const [price, setPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const addOrder = useSmartOrdersStore((s) => s.addOrder);
  const showToast = useToastStore((s) => s.show);
  const amountNum = parseFloat(amount) || 0;
  const isOption = useMemo(() => isOptionInstrument(instrument), [instrument]);

  const uiOverrides = useMemo<UiOverrides>(() => {
    const o: UiOverrides = {};
    const num = (s: string) => (s === '' ? undefined : parseFloat(s));
    const t = num(timeoutS);
    const mxl = num(maxIocLevels);
    const plp = num(priceLimitPctUi);
    const plt = num(priceLimitTicks);
    const pli = num(priceLimitIv);
    if (t !== undefined) o.timeout = t;
    if (mxl !== undefined) o.maxIocLevels = mxl;
    if (isOption) {
      if (plt !== undefined) o.priceLimitTicks = plt;
      if (pli !== undefined) o.priceLimitIv = pli;
    } else {
      if (plp !== undefined) o.priceLimitPct = plp;
    }
    return o;
  }, [timeoutS, maxIocLevels, priceLimitPctUi, priceLimitTicks, priceLimitIv, isOption]);

  const overrides = useMemo<SmartOrderOverrides>(
    () => overridesToApi(uiOverrides),
    [uiOverrides],
  );

  const handleSubmit = useCallback(async () => {
    if (amountNum <= 0) return;
    const validationError = validateOverrides(overrides);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'smart') {
        const order = await createSmartOrder({
          instrument_name: instrument,
          direction,
          amount: amountNum,
          intent,
          overrides: Object.keys(overrides).length > 0 ? overrides : undefined,
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
      setShowConfirm(false);
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      showToast('error', msg);
    } finally {
      setSubmitting(false);
    }
  }, [amountNum, mode, instrument, direction, intent, overrides, price, addOrder, showToast]);

  const onClickPrimary = () => {
    if (amountNum <= 0) return;
    if (mode === 'smart') {
      const validationError = validateOverrides(overrides);
      if (validationError) {
        setError(validationError);
        return;
      }
      setError(null);
      setShowConfirm(true);
    } else {
      handleSubmit();
    }
  };

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
        <div className="space-y-2">
          <div className="flex gap-2">
            {(['standard', 'urgent'] as Intent[]).map((i) => (
              <button
                key={i}
                onClick={() => setIntent(i)}
                className={`flex-1 py-2 rounded-lg text-xs font-bold tracking-wide transition-colors ${
                  intent === i
                    ? i === 'urgent'
                      ? 'bg-loss text-white'
                      : 'bg-primary text-white'
                    : 'bg-cream text-secondary hover:text-primary'
                }`}
              >
                {i === 'standard' ? 'Standard' : 'Urgent'}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-secondary leading-snug">
            {INTENT_BLURB[intent]}
          </p>

          <button
            onClick={() => setAdvancedOpen((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-secondary uppercase tracking-wider font-semibold hover:text-primary"
          >
            {advancedOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Advanced
          </button>

          {advancedOpen && (
            <div className="space-y-2.5 pt-1.5 pb-1 border-t border-divider/60">
              <div className="grid grid-cols-2 gap-2 mt-2">
                <NumberField
                  label={OVERRIDE_DISPLAY.timeout.label}
                  unit={OVERRIDE_DISPLAY.timeout.unit}
                  tooltip={OVERRIDE_DISPLAY.timeout.tooltip}
                  value={timeoutS}
                  onChange={setTimeoutS}
                  placeholder={String(OVERRIDE_DISPLAY.timeout.displayDefault)}
                />
                <NumberField
                  label={OVERRIDE_DISPLAY.maxIocLevels.label}
                  tooltip={OVERRIDE_DISPLAY.maxIocLevels.tooltip}
                  value={maxIocLevels}
                  onChange={setMaxIocLevels}
                  placeholder={String(OVERRIDE_DISPLAY.maxIocLevels.displayDefault)}
                />
              </div>
              {isOption ? (
                <div className="grid grid-cols-2 gap-2">
                  <NumberField
                    label={OVERRIDE_DISPLAY.priceLimitTicks.label}
                    tooltip={OVERRIDE_DISPLAY.priceLimitTicks.tooltip}
                    value={priceLimitTicks}
                    onChange={setPriceLimitTicks}
                    placeholder={String(OVERRIDE_DISPLAY.priceLimitTicks.displayDefault)}
                  />
                  <NumberField
                    label={OVERRIDE_DISPLAY.priceLimitIv.label}
                    unit={OVERRIDE_DISPLAY.priceLimitIv.unit}
                    tooltip={OVERRIDE_DISPLAY.priceLimitIv.tooltip}
                    value={priceLimitIv}
                    onChange={setPriceLimitIv}
                    step={OVERRIDE_DISPLAY.priceLimitIv.step}
                    placeholder={String(OVERRIDE_DISPLAY.priceLimitIv.displayDefault)}
                  />
                </div>
              ) : (
                <NumberField
                  label={OVERRIDE_DISPLAY.priceLimitPct.label}
                  unit={OVERRIDE_DISPLAY.priceLimitPct.unit}
                  tooltip={OVERRIDE_DISPLAY.priceLimitPct.tooltip}
                  value={priceLimitPctUi}
                  onChange={setPriceLimitPctUi}
                  step={OVERRIDE_DISPLAY.priceLimitPct.step}
                  placeholder={String(OVERRIDE_DISPLAY.priceLimitPct.displayDefault)}
                />
              )}
            </div>
          )}
        </div>
      )}

      {error && <div className="text-xs text-loss font-medium mt-1">{error}</div>}

      <button
        onClick={onClickPrimary}
        disabled={submitting || amountNum <= 0}
        className={`w-full py-3 rounded-lg text-sm font-bold tracking-wide transition-all disabled:opacity-50 shadow-sm mt-2 ${
          direction === 'buy'
            ? 'bg-profit text-white hover:bg-profit/90'
            : 'bg-loss text-white hover:bg-loss/90'
        }`}
      >
        {submitting
          ? 'Submitting...'
          : mode === 'smart'
            ? `${intent === 'urgent' ? 'Urgent' : 'Smart'} ${direction}`
            : `${direction} ${instrument.split('-')[0]}`}
      </button>

      {showConfirm && mode === 'smart' && (
        <div
          className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center"
          onClick={() => setShowConfirm(false)}
        >
          <div
            className="bg-white rounded-card shadow-popup p-6 w-[380px] max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-primary mb-4">Confirm Smart Order</h3>
            <div className="space-y-2 text-sm">
              <Row label="Instrument" value={<span className="font-mono">{instrument}</span>} />
              <Row
                label="Direction"
                value={
                  <span className={`font-semibold ${direction === 'buy' ? 'text-profit' : 'text-loss'}`}>
                    {direction.toUpperCase()}
                  </span>
                }
              />
              <Row label="Amount" value={<span className="font-mono">{amountNum}</span>} />
              <Row
                label="Intent"
                value={
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      intent === 'urgent' ? 'bg-loss-bg text-loss' : 'bg-blue-100 text-blue-800'
                    }`}
                  >
                    {intent.toUpperCase()}
                  </span>
                }
              />
              {Object.entries(uiOverrides).length > 0 && (
                <div className="border-t border-divider pt-2 mt-2 space-y-1">
                  <div className="text-[10px] text-secondary uppercase tracking-wider font-semibold">
                    Advanced
                  </div>
                  {Object.entries(uiOverrides).map(([uiKey, v]) => {
                    const entry = OVERRIDE_DISPLAY[uiKey];
                    if (!entry) return null;
                    const display =
                      typeof v === 'number'
                        ? `${v}${entry.unit ? entry.unit : ''}`
                        : String(v);
                    return (
                      <Row
                        key={uiKey}
                        label={entry.label}
                        value={<span className="font-mono">{display}</span>}
                      />
                    );
                  })}
                </div>
              )}
            </div>
            <div className="flex gap-2 mt-6">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 py-2.5 rounded-lg border border-divider text-secondary text-sm font-semibold hover:bg-cream"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className={`flex-1 py-2.5 rounded-lg text-white text-sm font-semibold disabled:opacity-50 ${
                  direction === 'buy' ? 'bg-profit hover:bg-profit/90' : 'bg-loss hover:bg-loss/90'
                }`}
              >
                {submitting ? 'Submitting...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-secondary text-xs">{label}</span>
      <span className="text-primary text-sm">{value}</span>
    </div>
  );
}

function Futures() {
  const instrument = useFuturesStore((s) => s.selectedInstrument);
  const chatOpen = useChatStore((s) => s.open);
  const isNarrow = useIsNarrowViewport();
  const compact = chatOpen && isNarrow;
  const [orderDirection, setOrderDirection] = useState<'buy' | 'sell'>('buy');
  const [orderBookPopoverOpen, setOrderBookPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover on outside click or Escape
  useEffect(() => {
    if (!orderBookPopoverOpen) return;
    const onMouseDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOrderBookPopoverOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOrderBookPopoverOpen(false);
    };
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [orderBookPopoverOpen]);

  return (
    <div className="trading-mode bg-cream pb-20">
      {/* Slim instrument selector row (page-local, not topbar) */}
      <div className="px-6 pt-3 pb-2">
        <div className="max-w-content mx-auto w-full">
          <FuturesInstrumentSelector />
        </div>
      </div>

      {/* Main Workspace — natural document flow, no viewport-lock */}
      <div className="px-6">
        <div className="flex max-w-content mx-auto w-full gap-6 min-w-0">

          {/* Left: TradingView Chart (fixed 540px height, auto-fills remaining width) */}
          <div className="flex-1 min-w-0">
            <Panel
              className="h-[540px]"
              header={<span className="text-lg font-semibold text-primary">Chart</span>}
              contentClassName="p-1 flex-1 min-h-0"
            >
              <div className="h-full overflow-hidden">
                <TradingViewWidget
                  symbol={instrument === 'ETH-PERPETUAL' ? 'DERIBIT:ETHUSD.P' : 'DERIBIT:BTCUSD.P'}
                  height="100%"
                />
              </div>
            </Panel>
          </div>

          {/* Right: Order Form (top, primary) + Order Book (bottom). Both natural height, no internal scrolling — page scrolls naturally if total exceeds viewport. */}
          <div className={`flex-shrink-0 flex flex-col gap-4 ${compact ? 'w-right-col-futures-compact' : 'w-right-col-futures'}`}>

            {/* Order Form — natural size, fully visible */}
            <Panel
              className="flex-shrink-0 relative"
              contentClassName="p-4"
              header={
                <div className="flex items-center justify-between">
                  <span className="text-lg font-semibold text-primary">Place Order</span>
                  {compact && (
                    <button
                      type="button"
                      onClick={() => setOrderBookPopoverOpen((v) => !v)}
                      aria-label="Toggle Order Book popover"
                      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold text-secondary hover:text-accent hover:bg-cream transition-colors"
                    >
                      <BookOpen size={12} />
                      Book
                    </button>
                  )}
                </div>
              }
            >
              <div className="flex gap-2 mb-3">
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

              {/* Order Book popover — appears in compact mode when triggered */}
              {compact && orderBookPopoverOpen && (
                <div
                  ref={popoverRef}
                  className="absolute right-0 top-12 z-30 w-72 bg-white border border-divider-strong rounded-card shadow-popup p-3"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs uppercase tracking-wider font-semibold text-primary">Order Book</span>
                    <button
                      type="button"
                      onClick={() => setOrderBookPopoverOpen(false)}
                      aria-label="Close order book"
                      className="p-0.5 rounded hover:bg-cream text-secondary"
                    >
                      <X size={12} />
                    </button>
                  </div>
                  <OrderBook instrument={instrument} depth={5} />
                </div>
              )}
            </Panel>

            {/* Order Book — natural size with enough room for all 5 levels (no internal scroll) */}
            {!compact && (
              <Panel
                className="flex-shrink-0"
                header={<span className="text-base font-semibold text-primary">Order Book</span>}
                contentClassName="p-3"
              >
                <OrderBook instrument={instrument} depth={5} />
              </Panel>
            )}

          </div>
        </div>
      </div>

      <SmartOrderBar />
    </div>
  );
}

export default Futures;
