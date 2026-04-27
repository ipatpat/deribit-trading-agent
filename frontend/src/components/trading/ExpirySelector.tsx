interface ExpiryInfo {
  timestamp: number;
  daysToExpiry: number;
  atmIv: number;
}

interface ExpirySelectorProps {
  expiries: ExpiryInfo[];
  selected: string;
  onSelect: (expiry: string) => void;
}

function formatExpiryDate(timestamp: number): string {
  const d = new Date(timestamp);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function ExpirySelector({ expiries, selected, onSelect }: ExpirySelectorProps) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {expiries.map((exp) => {
        const key = String(exp.timestamp);
        const isSelected = selected === key;
        return (
          <button
            key={key}
            onClick={() => onSelect(key)}
            className={`flex-shrink-0 px-4 py-2 rounded-lg text-xs font-medium transition-colors ${
              isSelected
                ? 'bg-primary text-white'
                : 'bg-white border border-divider text-secondary hover:text-primary hover:border-primary'
            }`}
          >
            <div className="font-semibold">{formatExpiryDate(exp.timestamp)}</div>
            <div className="flex gap-2 mt-0.5 font-mono">
              <span>{exp.daysToExpiry}d</span>
              <span>IV {exp.atmIv.toFixed(1)}%</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default ExpirySelector;
