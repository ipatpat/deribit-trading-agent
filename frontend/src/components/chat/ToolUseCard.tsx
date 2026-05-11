import { useState } from 'react';
import { Wrench, Check, X, Loader2, ChevronDown, ChevronRight } from 'lucide-react';

interface ToolUseCardProps {
  name: string;
  input: unknown;
  status?: 'pending' | 'success' | 'error';
  result?: unknown;
  isError?: boolean;
}

/**
 * Visual card for a single tool invocation in a chat message.
 * - Streaming: spinner + "calling..."
 * - Success: ✓ icon + collapsed result preview, expandable
 * - Error: ✗ icon + red error message
 */
function ToolUseCard({ name, input, status = 'pending', result, isError }: ToolUseCardProps) {
  const [expanded, setExpanded] = useState(false);

  const statusIcon =
    status === 'pending' ? (
      <Loader2 size={12} className="animate-spin text-secondary" />
    ) : status === 'error' || isError ? (
      <X size={12} className="text-loss" />
    ) : (
      <Check size={12} className="text-profit" />
    );

  const inputJson = JSON.stringify(input ?? {}, null, 0);
  const inputPreview = inputJson.length > 60 ? inputJson.slice(0, 60) + '...' : inputJson;

  const resultJson =
    result === undefined || result === null
      ? null
      : typeof result === 'string'
        ? result
        : JSON.stringify(result, null, 2);
  const resultPreview =
    resultJson === null
      ? null
      : resultJson.length > 80
        ? resultJson.slice(0, 80).replace(/\n/g, ' ') + '...'
        : resultJson.replace(/\n/g, ' ');

  return (
    <div className="my-2 border border-divider rounded-lg bg-cream-light overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-cream/50">
        <Wrench size={11} className="text-secondary flex-shrink-0" />
        <span className="font-mono text-[11px] font-semibold text-primary flex-1 truncate">
          {name}
        </span>
        {statusIcon}
      </div>
      <div className="px-3 py-1.5 font-mono text-[10px] text-secondary border-t border-divider/50">
        <span className="text-disabled">args: </span>
        {inputPreview || '{}'}
      </div>
      {resultJson !== null && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={`w-full flex items-center gap-1 px-3 py-1.5 text-[10px] font-medium border-t border-divider/50 hover:bg-cream transition-colors ${
              isError ? 'text-loss' : 'text-secondary'
            }`}
          >
            {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            <span className="font-mono truncate flex-1 text-left">
              {expanded ? 'collapse' : resultPreview}
            </span>
          </button>
          {expanded && (
            <pre className="px-3 py-2 font-mono text-[10px] text-primary bg-white border-t border-divider/50 max-h-48 overflow-auto whitespace-pre-wrap">
              {resultJson}
            </pre>
          )}
        </>
      )}
    </div>
  );
}

export default ToolUseCard;
