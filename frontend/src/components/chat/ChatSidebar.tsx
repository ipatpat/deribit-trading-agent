import { useEffect, useRef, useState } from 'react';
import { X, Send, Sparkles, StopCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatStore, type ChatMessage, type ContentBlock } from '../../stores/chat';
import { useSmartOrdersStore } from '../../stores/smartOrders';
import { getAiAgentConfig } from '../../api/aiAgent';
import ChatColdStart from './ChatColdStart';
import ToolUseCard from './ToolUseCard';

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  // Group tool_use + tool_result by id so we can render unified cards
  const toolResults = new Map<string, ContentBlock>();
  for (const b of message.content) {
    if (b.type === 'tool_result') {
      toolResults.set(b.tool_use_id, b);
    }
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[90%] ${isUser ? 'bg-primary text-white' : 'bg-cream'} rounded-lg px-3 py-2 text-sm`}>
        {message.content.map((block, idx) => {
          if (block.type === 'text') {
            // User messages are plain text; assistant messages use markdown.
            if (isUser) {
              return (
                <div key={idx} className="whitespace-pre-wrap break-words">
                  {block.text}
                </div>
              );
            }
            return (
              <div key={idx} className="prose-chat break-words">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                    table: ({ children }) => (
                      <div className="overflow-x-auto my-2">
                        <table className="min-w-full text-xs border-collapse">{children}</table>
                      </div>
                    ),
                    thead: ({ children }) => <thead className="bg-cream-dark/50">{children}</thead>,
                    th: ({ children }) => (
                      <th className="border border-divider px-2 py-1 text-left font-semibold">{children}</th>
                    ),
                    td: ({ children }) => (
                      <td className="border border-divider/60 px-2 py-1 font-mono">{children}</td>
                    ),
                    code: ({ children, ...props }) => {
                      const isInline = !(props as { node?: { position?: { start: { line: number }; end: { line: number } } } }).node?.position
                        || ((props as any).node.position.start.line === (props as any).node.position.end.line);
                      return isInline ? (
                        <code className="px-1 py-0.5 rounded bg-cream-dark/50 font-mono text-[11px]">{children}</code>
                      ) : (
                        <pre className="my-2 p-2 rounded bg-cream-dark/50 overflow-x-auto">
                          <code className="font-mono text-[11px]">{children}</code>
                        </pre>
                      );
                    },
                    ul: ({ children }) => <ul className="list-disc ml-4 my-2 space-y-0.5">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal ml-4 my-2 space-y-0.5">{children}</ol>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    em: ({ children }) => <em className="italic">{children}</em>,
                  }}
                >
                  {block.text}
                </ReactMarkdown>
              </div>
            );
          }
          if (block.type === 'tool_use') {
            const result = toolResults.get(block.id);
            return (
              <ToolUseCard
                key={block.id}
                name={block.tool_name}
                input={block.tool_input}
                status={block.status}
                result={result?.type === 'tool_result' ? result.output : undefined}
                isError={result?.type === 'tool_result' ? result.is_error : false}
              />
            );
          }
          // tool_result is rendered via the matched tool_use card
          return null;
        })}
      </div>
    </div>
  );
}

function ChatSidebar() {
  const messages = useChatStore((s) => s.messages);
  const draft = useChatStore((s) => s.draft);
  const setDraft = useChatStore((s) => s.setDraft);
  const close = useChatStore((s) => s.close);
  const loading = useChatStore((s) => s.loading);
  const errorMsg = useChatStore((s) => s.error);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abort = useChatStore((s) => s.abort);

  const smartBarVisible = useSmartOrdersStore((s) => s.orders.length > 0);

  const [configLoading, setConfigLoading] = useState(true);
  const [configured, setConfigured] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Check AI agent config on mount; refresh after loading state settles
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await getAiAgentConfig();
        if (cancelled) return;
        const ok = !!(cfg.endpoint && cfg.model && cfg.api_key_set) || !!cfg.env_fallback_available;
        setConfigured(ok);
      } catch {
        if (!cancelled) setConfigured(false);
      } finally {
        if (!cancelled) setConfigLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, loading]);

  const handleSend = () => {
    if (!draft.trim() || loading) return;
    void sendMessage(draft);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <aside
      className="fixed right-0 w-chat-sidebar bg-white border-l border-divider flex flex-col z-40"
      style={{
        top: 'var(--topbar-height)',
        bottom: smartBarVisible ? 'var(--smartbar-height)' : 0,
      }}
      aria-label="Chat sidebar"
    >
      <header className="h-14 px-4 flex items-center justify-between border-b border-divider flex-shrink-0">
        <span className="flex items-center gap-2 text-sm font-semibold text-primary">
          <Sparkles size={14} className="text-accent" />
          AI Assistant
        </span>
        <button
          type="button"
          onClick={close}
          aria-label="Close chat"
          className="p-1.5 rounded hover:bg-cream text-secondary hover:text-primary transition-colors"
        >
          <X size={16} />
        </button>
      </header>

      {configLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 rounded-full border-2 border-cream border-t-accent animate-spin" />
        </div>
      ) : !configured ? (
        <ChatColdStart />
      ) : (
        <>
          <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
            {messages.length === 0 ? (
              <div className="text-secondary text-sm p-8 text-center">
                Ask me about market data, your portfolio, or option strategies.
              </div>
            ) : (
              messages.map((m) => <MessageBubble key={m.id} message={m} />)
            )}
            {errorMsg && (
              <div className="text-loss text-xs bg-loss-bg border border-loss/20 rounded-lg p-2">
                {errorMsg}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-divider p-3 flex-shrink-0">
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={loading ? 'Streaming...' : 'Ask anything (Enter to send)'}
                rows={2}
                disabled={loading}
                className="flex-1 resize-none border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent disabled:bg-cream disabled:text-secondary"
              />
              {loading ? (
                <button
                  type="button"
                  onClick={abort}
                  aria-label="Stop"
                  className="p-2 rounded-lg bg-loss-bg text-loss hover:bg-loss/20 transition-colors"
                >
                  <StopCircle size={16} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={!draft.trim()}
                  aria-label="Send message"
                  className="p-2 rounded-lg bg-primary text-white hover:bg-primary/90 disabled:bg-cream disabled:text-secondary disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={16} />
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}

export default ChatSidebar;
