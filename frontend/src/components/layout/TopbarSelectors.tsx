import { useEffect } from 'react';
import { useFuturesStore, FUTURES_INSTRUMENTS } from '../../stores/futures';
import { useOptionsStore, type OptionCurrency } from '../../stores/options';

const OPTION_CURRENCIES: OptionCurrency[] = ['BTC', 'ETH'];

export function FuturesTopbarSelector() {
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
            className={`px-3 h-9 rounded-full text-sm font-bold transition-colors ${
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

export function OptionsTopbarSelector() {
  const currency = useOptionsStore((s) => s.currency);
  const setCurrency = useOptionsStore((s) => s.setCurrency);
  const selectedExpiry = useOptionsStore((s) => s.selectedExpiry);
  const setSelectedExpiry = useOptionsStore((s) => s.setSelectedExpiry);
  const expiries = useOptionsStore((s) => s.expiries);
  const loading = useOptionsStore((s) => s.expiriesLoading);
  const fetchExpiries = useOptionsStore((s) => s.fetchExpiries);

  useEffect(() => {
    if (expiries.length === 0 && !loading) {
      void fetchExpiries();
    }
  }, [expiries.length, loading, fetchExpiries]);

  return (
    <div className="flex items-center gap-3 min-w-0">
      <div className="flex gap-1 flex-shrink-0">
        {OPTION_CURRENCIES.map((c) => {
          const active = currency === c;
          return (
            <button
              key={c}
              onClick={() => setCurrency(c)}
              className={`px-3 h-9 rounded-full text-sm font-bold transition-colors ${
                active
                  ? 'bg-primary text-white'
                  : 'text-secondary hover:text-primary hover:bg-cream'
              }`}
            >
              {c}
            </button>
          );
        })}
      </div>

      <div className="w-px h-6 bg-divider flex-shrink-0" />

      <div className="flex gap-1.5 overflow-x-auto min-w-0 py-1">
        {loading && expiries.length === 0
          ? Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-8 w-20 bg-cream rounded-full animate-pulse flex-shrink-0"
              />
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
                  className={`flex-shrink-0 h-8 px-3 rounded-full text-xs font-medium transition-colors flex items-center gap-1.5 ${
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
