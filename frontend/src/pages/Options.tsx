import { useState, useEffect, useMemo } from 'react';
import { Eye, EyeOff, ChevronsUpDown, ChevronsDownUp } from 'lucide-react';
import Panel from '../components/common/Panel';
import OptionChain from '../components/trading/OptionChain';
import IVSmile from '../components/charts/IVSmile';
import TermStructure from '../components/charts/TermStructure';
import TradeTicket from '../components/trading/TradeTicket';
import TradeModal from '../components/trading/TradeModal';
import { getOptionChain } from '../api/client';
import type { PayoffLeg } from '../api/client';
import type { OptionChainRow } from '../types/api';
import { useToastStore } from '../stores/toast';
import { useOptionsStore, type OptionCurrency } from '../stores/options';
import { useChatStore } from '../stores/chat';
import { useIsNarrowViewport } from '../hooks/useViewportWidth';

const OPTION_CURRENCIES: OptionCurrency[] = ['BTC', 'ETH'];

function OptionsSelectorRow() {
  const currency = useOptionsStore((s) => s.currency);
  const setCurrency = useOptionsStore((s) => s.setCurrency);
  const selectedExpiry = useOptionsStore((s) => s.selectedExpiry);
  const setSelectedExpiry = useOptionsStore((s) => s.setSelectedExpiry);
  const expiries = useOptionsStore((s) => s.expiries);
  const loading = useOptionsStore((s) => s.expiriesLoading);

  return (
    <div className="flex items-center gap-3 min-w-0">
      <div className="flex gap-1 flex-shrink-0">
        {OPTION_CURRENCIES.map((c) => {
          const active = currency === c;
          return (
            <button
              key={c}
              onClick={() => setCurrency(c)}
              className={`px-3 h-8 rounded-full text-sm font-bold transition-colors ${
                active ? 'bg-primary text-white' : 'text-secondary hover:text-primary hover:bg-cream'
              }`}
            >
              {c}
            </button>
          );
        })}
      </div>

      <div className="w-px h-5 bg-divider flex-shrink-0" />

      <div className="flex gap-1.5 overflow-x-auto min-w-0 py-1">
        {loading && expiries.length === 0
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-7 w-20 bg-cream rounded-full animate-pulse flex-shrink-0" />
            ))
          : expiries.map((exp) => {
              const key = String(exp.timestamp);
              const active = selectedExpiry === key;
              const dateLabel = new Date(exp.timestamp).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
              });
              return (
                <button
                  key={key}
                  onClick={() => setSelectedExpiry(key)}
                  className={`flex-shrink-0 h-7 px-3 rounded-full text-xs font-medium transition-colors flex items-center gap-1.5 ${
                    active
                      ? 'bg-primary text-white'
                      : 'bg-white border border-divider text-secondary hover:text-primary hover:border-primary'
                  }`}
                >
                  <span className="font-semibold">{dateLabel}</span>
                  <span className="font-mono">{exp.daysToExpiry}d</span>
                  {exp.atmIv > 0 && <span className="font-mono">{exp.atmIv.toFixed(0)}%</span>}
                </button>
              );
            })}
      </div>
    </div>
  );
}

function Options() {
  const currency = useOptionsStore((s) => s.currency);
  const expiries = useOptionsStore((s) => s.expiries);
  const selectedExpiry = useOptionsStore((s) => s.selectedExpiry);
  const expiriesLoading = useOptionsStore((s) => s.expiriesLoading);
  const fetchExpiries = useOptionsStore((s) => s.fetchExpiries);
  const [chainData, setChainData] = useState<OptionChainRow[]>([]);
  const [chainError, setChainError] = useState<string | null>(null);
  const [legs, setLegs] = useState<PayoffLeg[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [chainShowAll, setChainShowAll] = useState(false);
  const [forceShowAnalytics, setForceShowAnalytics] = useState(false);
  const chatOpen = useChatStore((s) => s.open);
  const isNarrow = useIsNarrowViewport();
  const compact = chatOpen && isNarrow && !forceShowAnalytics;
  const showToast = useToastStore((s) => s.show);

  const addLeg = (instrument: string, direction: 'buy' | 'sell') => {
    setLegs((prev) => [...prev, { instrument, direction, amount: 1 }]);
  };

  const addFuturesLeg = (direction: 'buy' | 'sell') => {
    setLegs((prev) => [...prev, { instrument: `${currency}-PERPETUAL`, direction, amount: 1 }]);
  };

  const removeLeg = (index: number) => {
    setLegs((prev) => prev.filter((_, i) => i !== index));
  };

  const clearLegs = () => {
    setLegs([]);
  };

  const toggleDirection = (index: number) => {
    setLegs((prev) =>
      prev.map((l, i) =>
        i === index
          ? { ...l, direction: l.direction === 'buy' ? 'sell' : 'buy' }
          : l,
      ),
    );
  };

  const changeAmount = (index: number, amount: number) => {
    setLegs((prev) =>
      prev.map((l, i) => (i === index ? { ...l, amount } : l)),
    );
  };

  // Trigger expiry fetch on mount + currency changes
  useEffect(() => {
    setLegs([]);
    void fetchExpiries();
  }, [currency, fetchExpiries]);

  // Fetch chain data when expiry changes (for IV smile data)
  useEffect(() => {
    const exp = expiries.find((e) => String(e.timestamp) === selectedExpiry);
    if (!exp) return;
    getOptionChain(currency, exp.expiry)
      .then((data: any) => {
        setChainData(Array.isArray(data) ? data : []);
        setChainError(null);
      })
      .catch(() => {
        setChainData([]);
        setChainError('Failed to load option chain data');
        showToast('error', 'Failed to load option chain data');
      });
  }, [currency, selectedExpiry, expiries]);

  // Derive IV smile data from chain (using actual IV from API)
  const ivSmileData = useMemo(() => {
    return chainData
      .filter((r: any) => r.call || r.put)
      .map((r: any) => {
        const ticker = r.call ?? r.put;
        const iv = ticker?.implied_volatility ?? ticker?.mark_iv ?? 0;
        return { strike: r.strike, iv };
      })
      .filter((d: any) => d.iv > 0);
  }, [chainData]);

  // ATM strike
  const atmStrike = useMemo(() => {
    if (chainData.length === 0) return undefined;
    const firstCall = chainData.find((r: any) => r.call)?.call as any;
    const firstPut = chainData.find((r: any) => r.put)?.put as any;
    const indexPrice =
      firstCall?.underlying_price ??
      firstCall?.index_price ??
      firstPut?.underlying_price ??
      firstPut?.index_price ??
      0;
    return chainData.reduce((prev, curr) =>
      Math.abs(curr.strike - indexPrice) < Math.abs(prev.strike - indexPrice)
        ? curr
        : prev,
    ).strike;
  }, [chainData]);

  // Term structure data from expiries
  const termStructureData = useMemo(() => {
    return expiries.map((e) => ({
      daysToExpiry: e.daysToExpiry,
      atmIv: e.atmIv,
    }));
  }, [expiries]);

  const selectedExpiryObj = expiries.find(
    (e) => String(e.timestamp) === selectedExpiry,
  );

  return (
    <div className="trading-mode bg-cream pb-20">
      {/* Slim selector row (page-local, not topbar): currency + expiries */}
      <div className="px-6 pt-3 pb-2">
        <div className="max-w-content mx-auto w-full">
          <OptionsSelectorRow />
        </div>
      </div>

      {/* Main Workspace: chain (flex-1) + analytics column (fixed 360px). Natural document flow. */}
      <div className="px-6">
        <div className="flex max-w-content mx-auto w-full gap-4 min-w-0">

          {/* Left: Option Chain — fixed 540px height to align with right column charts */}
          <div className="flex-1 min-w-0">
            <Panel
              className="h-[540px] flex flex-col"
              header={
                <div className="flex items-center justify-between text-lg">
                  <span className="font-semibold text-primary">
                    Option Chain {selectedExpiryObj && <span className="text-secondary ml-2 font-normal">{selectedExpiryObj.expiry}</span>}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => addFuturesLeg('buy')}
                      title={`Add ${currency}-PERPETUAL long leg to combo`}
                      className="px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold text-profit hover:bg-profit-bg transition-colors"
                    >
                      + Long Perp
                    </button>
                    <button
                      type="button"
                      onClick={() => addFuturesLeg('sell')}
                      title={`Add ${currency}-PERPETUAL short leg to combo`}
                      className="px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold text-loss hover:bg-loss-bg transition-colors"
                    >
                      + Short Perp
                    </button>
                    <span className="w-px h-4 bg-divider" />
                    <button
                      type="button"
                      onClick={() => setChainShowAll((v) => !v)}
                      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold text-secondary hover:text-accent hover:bg-cream transition-colors"
                    >
                      {chainShowAll ? <ChevronsDownUp size={12} /> : <ChevronsUpDown size={12} />}
                      {chainShowAll ? 'ATM ±10' : 'Show all'}
                    </button>
                    {chatOpen && isNarrow && (
                      <button
                        type="button"
                        onClick={() => setForceShowAnalytics((v) => !v)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold text-secondary hover:text-accent hover:bg-cream transition-colors"
                      >
                        {forceShowAnalytics ? <EyeOff size={12} /> : <Eye size={12} />}
                        {forceShowAnalytics ? 'Hide analytics' : 'Show analytics'}
                      </button>
                    )}
                    {chainError && !expiriesLoading && <span className="text-loss text-sm font-medium">{chainError}</span>}
                  </div>
                </div>
              }
              contentClassName="p-0 flex-1 min-h-0"
            >
              <OptionChain
                currency={currency}
                expiry={selectedExpiryObj?.expiry ?? ''}
                showAll={chainShowAll}
                onSelectOption={(instrument, direction) =>
                  addLeg(instrument, direction)
                }
              />
            </Panel>
          </div>

          {/* Right: Analytics column (IV Smile + Term Structure stacked); each chart renders at natural height — no internal scroll. Collapsed in chat-compact. */}
          {!compact && (
          <div className="w-[360px] flex-shrink-0 flex flex-col gap-4">
            <Panel
              className="flex-shrink-0"
              header={<span className="text-base font-semibold text-primary">IV Smile</span>}
              contentClassName="p-3"
            >
              {ivSmileData.length > 0 ? (
                <div className="h-[260px]">
                  <IVSmile data={ivSmileData} atmStrike={atmStrike} />
                </div>
              ) : (
                <div className="h-[260px] flex items-center justify-center text-secondary text-sm">
                  No IV data
                </div>
              )}
            </Panel>
            <Panel
              className="flex-shrink-0"
              header={<span className="text-base font-semibold text-primary">Term Structure</span>}
              contentClassName="p-3"
            >
              {termStructureData.length > 0 ? (
                <div className="h-[240px]">
                  <TermStructure data={termStructureData} />
                </div>
              ) : (
                <div className="h-[240px] flex items-center justify-center text-secondary text-sm">
                  No term structure data
                </div>
              )}
            </Panel>
          </div>
          )}
        </div>
      </div>

      <TradeTicket
        legs={legs}
        onRemoveLeg={removeLeg}
        onClear={clearLegs}
        onReview={() => setIsModalOpen(true)}
      />

      <TradeModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        legs={legs}
        onRemoveLeg={removeLeg}
        onToggleDirection={toggleDirection}
        onChangeAmount={changeAmount}
      />
    </div>
  );
}

export default Options;
