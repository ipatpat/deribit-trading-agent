import { Key } from 'lucide-react';
import { Link } from 'react-router-dom';

const SAMPLE_PROMPTS = [
  "What's the BTC perp price?",
  "Show me the BTC option market",
  "Analyze a long straddle on BTC",
];

/**
 * Shown inside ChatSidebar when AI Agent is not configured (missing
 * endpoint / model / api_key). Stays scoped to the sidebar — never a
 * page-level banner.
 */
function ChatColdStart() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
      <div className="w-12 h-12 rounded-full bg-cream flex items-center justify-center mb-4">
        <Key size={20} className="text-secondary" />
      </div>
      <p className="text-sm font-semibold text-primary mb-2">
        Configure AI to start chatting
      </p>
      <p className="text-xs text-secondary mb-5 max-w-[260px]">
        Endpoint, model, and API key are needed in Settings → AI Agent.
      </p>
      <Link
        to="/settings#ai-agent"
        className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors"
      >
        Open Settings →
      </Link>

      <div className="mt-8 w-full max-w-[260px] text-left">
        <p className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
          Try asking…
        </p>
        <ul className="space-y-1.5">
          {SAMPLE_PROMPTS.map((p) => (
            <li key={p} className="text-xs text-secondary italic">
              · "{p}"
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default ChatColdStart;
