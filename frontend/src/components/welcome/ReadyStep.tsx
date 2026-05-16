import { Check, MinusCircle, ArrowRight } from 'lucide-react';
import { useAccountsStore } from '../../stores/accounts';
import type { AiOutcome } from './AiAgentStep';
import type { AiAgentConfigPublic } from '../../api/aiAgent';

interface ReadyStepProps {
  aiOutcome: AiOutcome;
  aiConfig: AiAgentConfigPublic | null;
  onBack: () => void;
  onEnter: () => void;
}

function ReadyStep({ aiOutcome, aiConfig, onBack, onEnter }: ReadyStepProps) {
  const accounts = useAccountsStore((s) => s.accounts);
  const activeId = useAccountsStore((s) => s.activeId);
  const account = accounts.find((a) => a.id === activeId);
  const envLabel = account?.is_production ? 'Production' : 'Paper Trade';

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-semibold text-primary mb-2 text-center">
        You're all set
      </h2>
      <p className="text-sm text-secondary mb-8 text-center">
        Review your configuration and head into the trading terminal.
      </p>

      <div className="rounded-card border border-divider bg-white p-5 space-y-3">
        {/* Deribit row */}
        <div className="flex items-start gap-3">
          <Check size={18} className="text-profit mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold">
              Deribit account
            </div>
            <div className="text-sm text-primary font-mono mt-0.5 truncate">
              {account ? account.alias : '—'}
              {account && (
                <span className="ml-2 text-overline text-secondary uppercase tracking-wider font-semibold border border-divider rounded px-1.5 py-0.5">
                  {envLabel}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* AI row */}
        <div className="flex items-start gap-3">
          {aiOutcome === 'skipped' ? (
            <MinusCircle size={18} className="text-secondary mt-0.5 shrink-0" />
          ) : (
            <Check size={18} className="text-profit mt-0.5 shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-overline text-secondary uppercase tracking-wider font-semibold">
              AI assistant
            </div>
            <div className="text-sm text-primary font-mono mt-0.5 truncate">
              {aiOutcome === 'saved' && aiConfig?.endpoint && (
                <>
                  {aiConfig.endpoint}
                  {aiConfig.model && <span className="text-secondary"> · {aiConfig.model}</span>}
                </>
              )}
              {aiOutcome === 'env' && (
                <span className="text-secondary">Using environment variable</span>
              )}
              {aiOutcome === 'skipped' && (
                <span className="text-secondary normal-case font-sans">
                  Skipped — configure later in Settings
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="text-xs font-semibold text-secondary hover:text-primary transition-colors"
        >
          ← Back to adjust
        </button>
        <button
          type="button"
          onClick={onEnter}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors"
        >
          Enter the trading terminal
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

export default ReadyStep;
