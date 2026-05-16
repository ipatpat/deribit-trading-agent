import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { chatStream, confirmTool as _confirmToolRequest, type ChatRequest } from '../api/aiAgent';
import { useAccountsStore } from './accounts';

export type Role = 'user' | 'assistant' | 'system';

export type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; tool_name: string; tool_input: unknown; id: string; status?: 'pending' | 'success' | 'error' }
  | { type: 'tool_result'; tool_use_id: string; output: unknown; is_error?: boolean }
  | {
      type: 'confirmation_pending';
      tool_call_id: string;
      tool_name: string;
      tool_input: unknown;
      summary: string;
    };

export interface ChatMessage {
  id: string;
  role: Role;
  content: ContentBlock[];
  ts: number;
}

export interface PageContext {
  route: string;
  instrument?: string;
}

export interface McpTool {
  name: string;
  description?: string;
  input_schema?: unknown;
}

interface ChatState {
  open: boolean;
  messages: ChatMessage[];
  draft: string;
  pageContext: PageContext;
  tools: McpTool[];

  // Write mode: master toggle for whether write tools are exposed to the LLM.
  // Persisted across reloads (users expect to stay in "trading session" mode).
  // Each individual write tool call still requires per-call confirmation.
  writeEnabled: boolean;

  // Streaming state (not persisted)
  loading: boolean;
  error: string | null;

  toggle: () => void;
  open_: () => void;
  close: () => void;
  appendMessage: (m: ChatMessage) => void;
  setDraft: (s: string) => void;
  setPageContext: (ctx: PageContext) => void;
  clearMessages: () => void;
  sendMessage: (text: string) => Promise<void>;
  abort: () => void;
  toggleWriteMode: () => void;
  confirmTool: (toolCallId: string, confirmed: boolean, reason?: string) => Promise<void>;
}

const CHAT_STORE_VERSION = 1;
const LEGACY_CHAT_STORE_KEY = 'chat-store';

function chatStoreKeyForAccount(accountId: string | null): string {
  // Anonymous (no active account) gets its own bucket so we don't bleed
  // a "fresh-install" conversation into the first real account on activate.
  return accountId ? `chat-store:${accountId}` : 'chat-store:_anonymous';
}

let _currentChatKey = chatStoreKeyForAccount(null);

/**
 * Rename the v3 single-key persisted chat into the first per-account bucket.
 * Idempotent: if the legacy key is gone or the new key already has data, no-op.
 * Call once during app boot, BEFORE the chat store hydrates.
 */
export function migrateLegacyChatStore(activeAccountId: string | null): void {
  try {
    const legacy = localStorage.getItem(LEGACY_CHAT_STORE_KEY);
    if (!legacy) return;
    const targetKey = chatStoreKeyForAccount(activeAccountId);
    if (localStorage.getItem(targetKey)) {
      // New bucket already exists — leave both alone so we don't clobber.
      localStorage.removeItem(LEGACY_CHAT_STORE_KEY);
      return;
    }
    localStorage.setItem(targetKey, legacy);
    localStorage.removeItem(LEGACY_CHAT_STORE_KEY);
  } catch {
    // localStorage unavailable → fall through to fresh state.
  }
}

// Module-level abort controller (one stream at a time)
let _activeController: AbortController | null = null;

function _makeId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// Build the payload sent to the backend (OpenAI-format, omitting our local-only fields).
function _serializeForBackend(messages: ChatMessage[]): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (const m of messages) {
    if (m.role === 'user') {
      const text = m.content
        .filter((b) => b.type === 'text')
        .map((b) => (b.type === 'text' ? b.text : ''))
        .join('');
      out.push({ role: 'user', content: text });
    } else if (m.role === 'assistant') {
      const text = m.content
        .filter((b) => b.type === 'text')
        .map((b) => (b.type === 'text' ? b.text : ''))
        .join('');
      const toolCalls = m.content
        .filter((b) => b.type === 'tool_use')
        .map((b) => {
          const t = b as Extract<ContentBlock, { type: 'tool_use' }>;
          return {
            id: t.id,
            type: 'function',
            function: { name: t.tool_name, arguments: JSON.stringify(t.tool_input ?? {}) },
          };
        });
      const msg: Record<string, unknown> = { role: 'assistant' };
      if (text) msg.content = text;
      if (toolCalls.length > 0) msg.tool_calls = toolCalls;
      if (text || toolCalls.length > 0) out.push(msg);

      // Emit tool result messages following the assistant
      for (const b of m.content) {
        if (b.type === 'tool_result') {
          out.push({
            role: 'tool',
            tool_call_id: b.tool_use_id,
            content: typeof b.output === 'string' ? b.output : JSON.stringify(b.output),
          });
        }
      }
    }
  }
  return out;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      open: false,
      messages: [],
      draft: '',
      pageContext: { route: '/' },
      tools: [],
      writeEnabled: false,
      loading: false,
      error: null,

      toggle: () => set((s) => ({ open: !s.open })),
      open_: () => set({ open: true }),
      close: () => set({ open: false }),
      appendMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
      setDraft: (draft) => set({ draft }),
      setPageContext: (pageContext) => set({ pageContext }),
      clearMessages: () => set({ messages: [], error: null }),
      toggleWriteMode: () => set((s) => ({ writeEnabled: !s.writeEnabled })),
      confirmTool: async (toolCallId, confirmed, reason) => {
        try {
          await _confirmToolRequest(toolCallId, confirmed, reason);
        } catch (err) {
          set({ error: `Failed to send confirmation: ${(err as Error).message}` });
        }
      },

      abort: () => {
        if (_activeController) {
          _activeController.abort();
          _activeController = null;
        }
        set({ loading: false });
      },

      sendMessage: async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed) return;

        // Abort any in-flight stream
        if (_activeController) {
          _activeController.abort();
          _activeController = null;
        }

        // Append user message
        const userMsg: ChatMessage = {
          id: _makeId(),
          role: 'user',
          content: [{ type: 'text', text: trimmed }],
          ts: Date.now(),
        };
        // Reserve an empty assistant message that we'll mutate as events stream in
        const assistantMsg: ChatMessage = {
          id: _makeId(),
          role: 'assistant',
          content: [],
          ts: Date.now(),
        };

        set((s) => ({
          messages: [...s.messages, userMsg, assistantMsg],
          draft: '',
          loading: true,
          error: null,
        }));

        const controller = new AbortController();
        _activeController = controller;

        // Snapshot all messages BEFORE the empty assistant placeholder for backend
        const stateAtSend = get();
        const backendMessages = _serializeForBackend(
          stateAtSend.messages.slice(0, -1), // exclude the placeholder
        );

        try {
          for await (const evt of chatStream(
            {
              messages: backendMessages as ChatRequest['messages'],
              page_context: stateAtSend.pageContext,
              write_enabled: stateAtSend.writeEnabled,
            },
            controller.signal,
          )) {
            // Apply each event by mutating the assistant message
            set((s) => {
              const msgs = [...s.messages];
              const lastIdx = msgs.length - 1;
              if (lastIdx < 0 || msgs[lastIdx].id !== assistantMsg.id) return s;
              const last = { ...msgs[lastIdx], content: [...msgs[lastIdx].content] };

              switch (evt.event) {
                case 'reasoning_delta': {
                  // DeepSeek-reasoner chain-of-thought; not surfaced in UI
                  // (stays on backend for next-turn echo-back).
                  break;
                }
                case 'text_delta': {
                  const last_block = last.content[last.content.length - 1];
                  if (last_block && last_block.type === 'text') {
                    last.content[last.content.length - 1] = {
                      ...last_block,
                      text: last_block.text + (evt.data.delta ?? ''),
                    };
                  } else {
                    last.content.push({ type: 'text', text: evt.data.delta ?? '' });
                  }
                  break;
                }
                case 'tool_use_start': {
                  last.content.push({
                    type: 'tool_use',
                    id: evt.data.id,
                    tool_name: evt.data.name,
                    tool_input: {},
                    status: 'pending',
                  });
                  break;
                }
                case 'tool_use_input': {
                  // Optional: could accumulate partial JSON for live display.
                  // For now we wait for tool_use_end which carries the full input.
                  break;
                }
                case 'tool_use_end': {
                  const tc = last.content.find(
                    (b) => b.type === 'tool_use' && (b as any).id === evt.data.id,
                  );
                  if (tc && tc.type === 'tool_use') {
                    (tc as any).tool_input = evt.data.input;
                  }
                  break;
                }
                case 'confirmation_required': {
                  // Push a confirmation_pending block — UI renders ConfirmationCard
                  // and the user's click triggers store.confirmTool(...) which
                  // POSTs the decision back to the paused agent loop.
                  last.content.push({
                    type: 'confirmation_pending',
                    tool_call_id: evt.data.tool_call_id,
                    tool_name: evt.data.name,
                    tool_input: evt.data.args,
                    summary: evt.data.summary,
                  });
                  break;
                }
                case 'tool_result': {
                  // Update the matching tool_use status
                  const tc = last.content.find(
                    (b) => b.type === 'tool_use' && (b as any).id === evt.data.tool_use_id,
                  );
                  if (tc && tc.type === 'tool_use') {
                    (tc as any).status = evt.data.is_error ? 'error' : 'success';
                  }
                  // If this tool_call had a pending confirmation, drop it now —
                  // the UI transitions from ConfirmationCard back to ToolUseCard.
                  last.content = last.content.filter(
                    (b) =>
                      !(
                        b.type === 'confirmation_pending'
                        && b.tool_call_id === evt.data.tool_use_id
                      ),
                  );
                  // Append a tool_result block for record
                  last.content.push({
                    type: 'tool_result',
                    tool_use_id: evt.data.tool_use_id,
                    output: evt.data.output,
                    is_error: evt.data.is_error,
                  });
                  break;
                }
                case 'done': {
                  // Finalize; nothing to mutate on the message itself.
                  break;
                }
                case 'error': {
                  return {
                    messages: msgs.slice(0, -1).concat({ ...last }),
                    loading: false,
                    error: evt.data.message ?? 'Unknown error',
                  };
                }
              }

              msgs[lastIdx] = last;
              return { messages: msgs };
            });

            if (evt.event === 'done' || evt.event === 'error') break;
          }
        } catch (err) {
          if ((err as DOMException)?.name === 'AbortError') {
            // Mark interrupted on the assistant message
            set((s) => {
              const msgs = [...s.messages];
              const lastIdx = msgs.length - 1;
              if (lastIdx >= 0 && msgs[lastIdx].id === assistantMsg.id) {
                const last = { ...msgs[lastIdx], content: [...msgs[lastIdx].content] };
                last.content.push({ type: 'text', text: '\n\n[interrupted by user]' });
                msgs[lastIdx] = last;
              }
              return { messages: msgs };
            });
          } else {
            set({ error: (err as Error).message ?? String(err) });
          }
        } finally {
          if (_activeController === controller) _activeController = null;
          set({ loading: false });
        }
      },
    }),
    {
      name: _currentChatKey,
      version: CHAT_STORE_VERSION,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        open: state.open,
        messages: state.messages,
        writeEnabled: state.writeEnabled,
      }),
      migrate: (persistedState, version) => {
        if (version < CHAT_STORE_VERSION) {
          return { open: false, messages: [], writeEnabled: false };
        }
        return persistedState as {
          open: boolean;
          messages: ChatMessage[];
          writeEnabled: boolean;
        };
      },
    },
  ),
);

/**
 * Swap the persist bucket to the given account's chat history, reset
 * writeEnabled back to false (re-arming the read-only gate), and rehydrate.
 * Idempotent when the target key already matches the current one.
 */
async function switchChatPersistKey(accountId: string | null): Promise<void> {
  const newKey = chatStoreKeyForAccount(accountId);
  if (newKey === _currentChatKey) return;
  _currentChatKey = newKey;

  // Flush the current bucket's in-memory state before switching, otherwise
  // the next rehydrate may write back over what was just there.
  useChatStore.persist.setOptions({ name: newKey });
  // Clear in-memory state so the rehydrate() result is what users see, not
  // a merged snapshot. writeEnabled forcibly resets to false on every switch.
  useChatStore.setState({
    messages: [],
    writeEnabled: false,
    error: null,
    loading: false,
  });
  await useChatStore.persist.rehydrate();
  // Always force writeEnabled false after rehydrate — even if the new
  // account had it persisted true, the user must re-arm intentionally.
  useChatStore.setState({ writeEnabled: false });
}

// Subscribe to activeId changes from the accounts store and react.
// The subscribe call here runs at module-load time — same time chat-store
// is created, before any boot-time fetchAccounts has run. Initial sync
// happens via the App boot path which calls switchChatPersistKey explicitly
// after fetchAccounts resolves.
useAccountsStore.subscribe((state, prev) => {
  if (state.activeId !== prev.activeId) {
    void switchChatPersistKey(state.activeId);
  }
});

export { switchChatPersistKey };
