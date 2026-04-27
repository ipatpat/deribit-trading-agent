import { useState, useEffect, useMemo } from 'react';
import Panel from '../components/common/Panel';
import OptionChain from '../components/trading/OptionChain';
import ExpirySelector from '../components/trading/ExpirySelector';
import IVSmile from '../components/charts/IVSmile';
import TermStructure from '../components/charts/TermStructure';
import TradeTicket from '../components/trading/TradeTicket';
import TradeModal from '../components/trading/TradeModal';
import { getExpiries, getOptionChain } from '../api/client';
import type { PayoffLeg } from '../api/client';
import type { OptionChainRow } from '../types/api';
import { useToastStore } from '../stores/toast';

const CURRENCIES = ['BTC', 'ETH'] as const;

interface ExpiryInfo {
  timestamp: number;
  expiry: string;
  daysToExpiry: number;
  atmIv: number;
}

function Options() {
  const [currency, setCurrency] = useState<string>('BTC');
  const [expiries, setExpiries] = useState<ExpiryInfo[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string>('');
  const [chainData, setChainData] = useState<OptionChainRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [chainError, setChainError] = useState<string | null>(null);
  const [legs, setLegs] = useState<PayoffLeg[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
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

  // Fetch expiries when currency changes
  useEffect(() => {
    setLoading(true);
    setLegs([]);
    getExpiries(currency)
      .then((data) => {
        const now = Date.now();
        const mapped: ExpiryInfo[] = data.map((e: any) => ({
          timestamp: e.timestamp,
          expiry: e.expiry,
          daysToExpiry: Math.max(1, Math.round((e.timestamp - now) / 86400000)),
          atmIv: e.atm_iv ?? e.atmIv ?? 0,
        }));
        setExpiries(mapped);
        if (mapped.length > 0) {
          setSelectedExpiry(String(mapped[0].timestamp));
        }
      })
      .catch(() => setExpiries([]))
      .finally(() => setLoading(false));
  }, [currency]);

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
    <div className="trading-mode flex flex-col h-[calc(100vh-var(--topbar-height))] overflow-hidden bg-cream">
      {/* Top Toolbar */}
      <div className="bg-white px-6 py-3 flex items-center gap-6 flex-shrink-0 z-10 border-b border-divider-strong rounded-lg">
        <div className="flex gap-1">
          {CURRENCIES.map((c) => (
            <button
              key={c}
              onClick={() => setCurrency(c)}
              className={`px-4 py-1.5 rounded-full text-sm font-bold transition-colors ${
                currency === c
                  ? 'bg-primary text-white'
                  : 'text-secondary hover:text-primary hover:bg-cream'
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-8 w-24 bg-cream rounded-full animate-pulse"
              />
            ))}
          </div>
        ) : (
          <ExpirySelector
            expiries={expiries}
            selected={selectedExpiry}
            onSelect={setSelectedExpiry}
          />
        )}
      </div>

      {/* Main Workspace (Full Width) */}
      <div className="flex flex-1 min-h-0 overflow-y-auto px-6 py-6 pb-24">
        <div className="flex-1 flex flex-col max-w-content mx-auto w-full gap-6">
          <Panel
            header={
              <div className="flex items-center justify-between text-lg">
                <span className="font-semibold text-primary">Option Chain {selectedExpiryObj && <span className="text-secondary ml-2 font-normal">{selectedExpiryObj.expiry}</span>}</span>
                {chainError && !loading && <span className="text-loss text-sm font-medium">{chainError}</span>}
              </div>
            }
            contentClassName="p-0"
          >
            <div className="min-h-[400px]">
              <OptionChain
                currency={currency}
                expiry={selectedExpiryObj?.expiry ?? ''}
                onSelectOption={(instrument, direction) =>
                  addLeg(instrument, direction)
                }
                onAddFutures={addFuturesLeg}
              />
            </div>
          </Panel>

          {/* Bottom Analysis Panels */}
          <div className="grid grid-cols-2 gap-6">
            <Panel
              header={<span className="text-base font-semibold text-primary">IV Smile</span>}
              contentClassName="p-4"
            >
              {ivSmileData.length > 0 ? (
                <IVSmile data={ivSmileData} atmStrike={atmStrike} />
              ) : (
                <div className="h-[200px] flex items-center justify-center text-secondary text-sm">
                  No IV data
                </div>
              )}
            </Panel>
            <Panel
              header={<span className="text-base font-semibold text-primary">Term Structure</span>}
              contentClassName="p-4"
            >
              {termStructureData.length > 0 ? (
                <TermStructure data={termStructureData} />
              ) : (
                <div className="h-[200px] flex items-center justify-center text-secondary text-sm">
                  No term structure data
                </div>
              )}
            </Panel>
          </div>
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
