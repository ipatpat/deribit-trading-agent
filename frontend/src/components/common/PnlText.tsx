import { formatUsd } from '../../utils/format';

interface PnlTextProps {
  value: number;
  className?: string;
}

function PnlText({ value, className = '' }: PnlTextProps) {
  const color = value >= 0 ? 'text-profit' : 'text-loss';
  const prefix = value > 0 ? '+' : '';

  return (
    <span className={`${color} ${className}`}>
      {prefix}{formatUsd(value)}
    </span>
  );
}

export default PnlText;
