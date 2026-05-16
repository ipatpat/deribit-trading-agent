import { useEffect } from 'react';
import { Sparkles } from 'lucide-react';
import * as Slider from '@radix-ui/react-slider';
import Card from '../components/common/Card';
import AccountList from '../components/account/AccountList';
import ReferralHint from '../components/account/ReferralHint';
import AiAgentForm from '../components/settings/AiAgentForm';
import { useSettingsStore, getReadableIntervals } from '../stores/settings';

function AiAgentCard() {
  useEffect(() => {
    if (window.location.hash === '#ai-agent') {
      requestAnimationFrame(() => {
        document.getElementById('ai-agent')?.scrollIntoView({ behavior: 'smooth' });
      });
    }
  }, []);

  return (
    <Card>
      <div id="ai-agent" className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4 flex items-center gap-2">
        <Sparkles size={14} className="text-accent" />
        AI Agent
      </div>
      <AiAgentForm />
    </Card>
  );
}

function Settings() {
  const { autoRefresh, speed, setAutoRefresh, setSpeed } = useSettingsStore();
  const readableIntervals = getReadableIntervals(speed);

  return (
    <div className="space-y-4">
      {/* Card 1: Accounts */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-1">
          Accounts
        </div>
        <p className="text-overline text-secondary mb-3">
          Manage your Deribit / Tibired trading accounts. Switch the active
          account from here or the top-right chip. Credentials are encrypted
          locally with your master password.
        </p>
        <ReferralHint variant="card" />
        <div className="mt-3">
          <AccountList />
        </div>
      </Card>

      {/* Card 2: Trading Client Configuration */}
      <Card>
        <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-4">
          Trading Client Configuration
        </div>

        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-primary font-medium">Auto Refresh</span>
          <div className="flex gap-1 bg-cream rounded-lg p-1">
            <button
              onClick={() => setAutoRefresh(true)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                autoRefresh ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              On
            </button>
            <button
              onClick={() => setAutoRefresh(false)}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                !autoRefresh ? 'bg-primary text-white' : 'text-secondary hover:text-primary'
              }`}
            >
              Off
            </button>
          </div>
        </div>

        {autoRefresh && (
          <div>
            <Slider.Root
              value={[speed]}
              onValueChange={([v]) => setSpeed(v)}
              min={0}
              max={1}
              step={0.05}
              className="relative flex items-center select-none touch-none w-full h-5"
            >
              <Slider.Track className="bg-cream-dark relative grow rounded-full h-1">
                <Slider.Range className="absolute bg-accent rounded-full h-full" />
              </Slider.Track>
              <Slider.Thumb className="block w-3.5 h-3.5 bg-white border-2 border-accent rounded-full focus:outline-none" />
            </Slider.Root>
            <div className="flex justify-between mt-0.5 text-overline text-disabled">
              <span>Slow</span>
              <span>Fast</span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-overline font-mono text-secondary">
              <span>Dashboard {readableIntervals.Dashboard}s</span>
              <span>Options {readableIntervals.Options}s</span>
              <span>OrderBook {readableIntervals.OrderBook}s</span>
              <span>Candles {readableIntervals.Candles}s</span>
              <span>Equity {readableIntervals.Equity}s</span>
            </div>
          </div>
        )}
      </Card>

      {/* Card 3: AI Agent Configuration */}
      <AiAgentCard />
    </div>
  );
}

export default Settings;
