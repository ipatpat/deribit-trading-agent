import { AI_NAME } from './identity';

/**
 * Shown between sendMessage and the first text_delta event. Particularly
 * important when the LLM is in a reasoning_content phase (deepseek-reasoner)
 * where the agent loop is busy but no surfaced output has arrived yet.
 */
function ThinkingPlaceholder() {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] bg-cream rounded-lg px-3 py-2 text-sm flex items-center gap-2">
        <span className="text-secondary text-xs">{AI_NAME} is thinking</span>
        <span className="thinking-dots flex gap-0.5">
          <span className="w-1 h-1 rounded-full bg-secondary thinking-dot" />
          <span className="w-1 h-1 rounded-full bg-secondary thinking-dot" />
          <span className="w-1 h-1 rounded-full bg-secondary thinking-dot" />
        </span>
      </div>
    </div>
  );
}

export default ThinkingPlaceholder;
