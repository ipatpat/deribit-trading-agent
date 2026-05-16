import { Check } from 'lucide-react';

export type WelcomeStep = 'deribit' | 'ai' | 'ready';

const ORDER: WelcomeStep[] = ['deribit', 'ai', 'ready'];
const LABELS: Record<WelcomeStep, string> = {
  deribit: 'Deribit',
  ai: 'AI',
  ready: 'Ready',
};

interface StepIndicatorProps {
  current: WelcomeStep;
  /** Set of steps the user has visited; controls back-navigation. */
  visited: Set<WelcomeStep>;
  onJump: (step: WelcomeStep) => void;
}

function StepIndicator({ current, visited, onJump }: StepIndicatorProps) {
  const currentIdx = ORDER.indexOf(current);

  return (
    <div className="flex items-center gap-3">
      {ORDER.map((step, idx) => {
        const done = idx < currentIdx;
        const active = step === current;
        const canJump = visited.has(step) && step !== current;

        return (
          <div key={step} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => canJump && onJump(step)}
              disabled={!canJump}
              className={`flex items-center gap-2 ${canJump ? 'cursor-pointer' : 'cursor-default'}`}
            >
              <span
                className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-semibold border transition-colors ${
                  done
                    ? 'bg-accent text-white border-accent'
                    : active
                    ? 'bg-primary text-white border-primary'
                    : 'bg-transparent text-secondary border-divider'
                }`}
              >
                {done ? <Check size={14} /> : idx + 1}
              </span>
              <span
                className={`text-sm font-medium ${
                  active ? 'text-primary' : done ? 'text-primary' : 'text-secondary'
                }`}
              >
                {LABELS[step]}
              </span>
            </button>
            {idx < ORDER.length - 1 && (
              <span
                className={`block w-10 h-px ${
                  idx < currentIdx ? 'bg-accent' : 'bg-divider'
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default StepIndicator;
