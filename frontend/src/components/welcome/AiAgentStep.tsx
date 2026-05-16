import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import AiAgentForm from '../settings/AiAgentForm';
import type { AiAgentConfigPublic } from '../../api/aiAgent';

export type AiOutcome = 'saved' | 'env' | 'skipped';

interface AiAgentStepProps {
  onBack: () => void;
  /** Called after the user saves or skips with the determined outcome. */
  onContinue: (outcome: AiOutcome) => void;
}

function AiAgentStep({ onBack, onContinue }: AiAgentStepProps) {
  const [cfg, setCfg] = useState<AiAgentConfigPublic | null>(null);
  const [reconfiguring, setReconfiguring] = useState(false);

  const apiKeySet = !!cfg?.api_key_set;
  const envFallback = !!cfg?.env_fallback_available && !apiKeySet;

  // Banner state machine
  const showSavedBanner = apiKeySet && !reconfiguring;
  const showEnvBanner = envFallback && !reconfiguring;

  // Skip button label varies by banner state.
  const skipLabel = showSavedBanner
    ? 'Use saved config & continue →'
    : showEnvBanner
    ? 'Use env config & continue →'
    : 'Skip for now';

  const handleSkip = () => {
    if (showSavedBanner) onContinue('saved');
    else if (showEnvBanner) onContinue('env');
    else onContinue('skipped');
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-8">
      {/* Left: form */}
      <div className="md:col-span-3">
        <h2 className="text-xl font-semibold text-primary mb-1 flex items-center gap-2">
          <Sparkles size={18} className="text-accent" />
          Configure your AI assistant
        </h2>
        <p className="text-sm text-secondary mb-5">
          Vida is optional. You can skip this step and configure it later in Settings.
        </p>

        {/* 3-state banner */}
        {showSavedBanner && (
          <div className="mb-4 p-3 rounded-card border border-profit/30 bg-profit-bg text-sm flex items-center justify-between">
            <span className="text-profit">
              Already configured (key ending in <span className="font-mono">…{cfg?.api_key_tail ?? ''}</span>).
            </span>
            <button
              type="button"
              onClick={() => setReconfiguring(true)}
              className="text-xs font-semibold text-profit hover:underline"
            >
              Reconfigure
            </button>
          </div>
        )}
        {showEnvBanner && (
          <div className="mb-4 p-3 rounded-card border border-accent/30 bg-accent/[0.08] text-sm text-primary">
            Detected API key from environment variable. You can skip this step or override below.
          </div>
        )}

        <AiAgentForm
          showEnvBanner={false}
          showSkipButton
          showClearButton={false}
          showWriteModeHint={false}
          primaryLabel="Save & Next"
          skipLabel={skipLabel}
          onConfigLoaded={setCfg}
          onSaved={() => {
            setReconfiguring(false);
            onContinue('saved');
          }}
          onSkip={handleSkip}
        />

        <div className="mt-5">
          <button
            type="button"
            onClick={onBack}
            className="text-xs font-semibold text-secondary hover:text-primary transition-colors"
          >
            ← Back
          </button>
        </div>
      </div>

      {/* Right: help sidebar */}
      <aside className="md:col-span-2 space-y-5 text-sm">
        <section>
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            Vida 兼容任何 OpenAI 协议的服务
          </div>
          <ul className="text-secondary leading-relaxed space-y-0.5">
            <li>• <span className="text-primary">DeepSeek</span>（默认推荐）</li>
            <li>• Zhipu GLM</li>
            <li>• OpenAI</li>
            <li>• vLLM / ollama 等本地服务</li>
          </ul>
        </section>

        <section>
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            环境变量
          </div>
          <p className="text-secondary leading-relaxed">
            如果你已在环境变量里设置过 <code className="font-mono text-xs text-primary">DEEPSEEK_API_KEY</code>，可以直接跳过这一步。
          </p>
        </section>

        <section className="p-3 rounded-card bg-accent/[0.06] border border-accent/20">
          <div className="text-sm text-primary leading-relaxed">
            <span className="font-semibold">💡 提示</span><br />
            AI 是放大器，不是必需品 —— 没配 AI 也能正常交易。
          </div>
        </section>
      </aside>
    </div>
  );
}

export default AiAgentStep;
