import { type PayoffLeg } from '../../api/client';

interface TradeTicketProps {
  legs: PayoffLeg[];
  onRemoveLeg: (index: number) => void;
  onClear: () => void;
  onReview: () => void;
}

function TradeTicket({ legs, onRemoveLeg, onClear, onReview }: TradeTicketProps) {
  if (legs.length === 0) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-white border border-divider shadow-popup rounded-lg p-4 flex items-center gap-6 z-40 transition-all duration-300">
      <div className="flex flex-col gap-1 max-h-[120px] overflow-y-auto pr-2">
        {legs.map((leg, i) => (
          <div key={`${leg.instrument}-${i}`} className="flex items-center gap-3 text-sm">
            <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${
              leg.direction === 'buy' ? 'bg-profit-bg text-profit' : 'bg-loss-bg text-loss'
            }`}>
              {leg.direction}
            </span>
            <span className="font-mono text-primary font-medium">{leg.instrument}</span>
            <span className="text-secondary">x{leg.amount}</span>
            <button
              onClick={() => onRemoveLeg(i)}
              className="text-disabled hover:text-loss ml-2 transition-colors"
              title="Remove leg"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      <div className="w-[1px] h-12 bg-divider" />

      <div className="flex items-center gap-3">
        <div className="flex flex-col">
          <span className="text-xs text-secondary uppercase tracking-wider font-semibold">Legs</span>
          <span className="text-lg font-mono font-bold text-primary">{legs.length}</span>
        </div>
        <button
          onClick={onReview}
          className="ml-4 px-6 py-2.5 bg-primary text-white rounded font-bold text-sm hover:bg-primary/90 transition-colors shadow-sm"
        >
          Review & Trade
        </button>
        <button
          onClick={onClear}
          className="px-3 py-2.5 text-secondary hover:text-primary rounded text-sm font-medium transition-colors"
        >
          Clear
        </button>
      </div>
    </div>
  );
}

export default TradeTicket;
