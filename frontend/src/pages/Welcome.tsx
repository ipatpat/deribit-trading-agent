import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAiAgentConfig, type AiAgentConfigPublic } from '../api/aiAgent';
import { useAccountsStore } from '../stores/accounts';
import StepIndicator, { type WelcomeStep } from '../components/welcome/StepIndicator';
import DeribitStep from '../components/welcome/DeribitStep';
import AiAgentStep, { type AiOutcome } from '../components/welcome/AiAgentStep';
import ReadyStep from '../components/welcome/ReadyStep';

function Welcome() {
  const navigate = useNavigate();
  const activeId = useAccountsStore((s) => s.activeId);
  const activate = useAccountsStore((s) => s.activate);

  const [step, setStep] = useState<WelcomeStep>('deribit');
  const [visited, setVisited] = useState<Set<WelcomeStep>>(new Set(['deribit']));
  const [aiOutcome, setAiOutcome] = useState<AiOutcome>('skipped');
  const [aiConfig, setAiConfig] = useState<AiAgentConfigPublic | null>(null);

  // Refresh AI config after Step 2 to render the right summary in Step 3.
  const refreshAiConfig = useCallback(async () => {
    try {
      setAiConfig(await getAiAgentConfig());
    } catch {
      /* non-fatal — Step 3 will show "Skipped" */
    }
  }, []);

  useEffect(() => {
    void refreshAiConfig();
  }, [refreshAiConfig]);

  const goTo = (next: WelcomeStep) => {
    setVisited((prev) => {
      const s = new Set(prev);
      s.add(next);
      return s;
    });
    setStep(next);
  };

  const handleDeribitSaved = async (newId: string) => {
    // The backend `POST /accounts` creates but does not activate the account.
    // Welcome must activate it so the rest of the app has an active account
    // when the user enters the trading terminal.
    try {
      await activate(newId);
    } catch {
      /* non-fatal — user can activate manually from Settings */
    }
    goTo('ai');
  };

  const handleAiContinue = async (outcome: AiOutcome) => {
    setAiOutcome(outcome);
    if (outcome === 'saved') await refreshAiConfig();
    goTo('ready');
  };

  const handleEnter = () => {
    navigate('/', { replace: true });
  };

  const showSkipSetup = activeId !== null;

  return (
    <div className="min-h-screen w-full bg-bg flex flex-col">
      {/* Top bar */}
      <header className="w-full border-b border-divider bg-white">
        <div className="max-w-[960px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <div className="text-lg font-semibold text-primary">Welcome to Vida</div>
            <div className="text-xs text-secondary">Let's get your trading terminal set up.</div>
          </div>
          {showSkipSetup && (
            <button
              type="button"
              onClick={() => navigate('/', { replace: true })}
              className="text-xs font-semibold text-secondary hover:text-primary transition-colors"
            >
              Skip setup →
            </button>
          )}
        </div>
        <div className="max-w-[960px] mx-auto px-6 pb-4">
          <StepIndicator current={step} visited={visited} onJump={goTo} />
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 w-full">
        <div className="max-w-[960px] mx-auto px-6 py-8">
          {step === 'deribit' && <DeribitStep onSaved={handleDeribitSaved} />}
          {step === 'ai' && (
            <AiAgentStep
              onBack={() => goTo('deribit')}
              onContinue={handleAiContinue}
            />
          )}
          {step === 'ready' && (
            <ReadyStep
              aiOutcome={aiOutcome}
              aiConfig={aiConfig}
              onBack={() => goTo('ai')}
              onEnter={handleEnter}
            />
          )}
        </div>
      </main>
    </div>
  );
}

export default Welcome;
