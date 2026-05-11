import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatStore } from '../../src/stores/chat';

const reset = () =>
  useChatStore.setState({
    open: false,
    messages: [],
    draft: '',
    pageContext: { route: '/' },
    tools: [],
    loading: false,
    error: null,
  });

describe('useChatStore', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('toggle flips open from false to true and back', () => {
    expect(useChatStore.getState().open).toBe(false);
    useChatStore.getState().toggle();
    expect(useChatStore.getState().open).toBe(true);
    useChatStore.getState().toggle();
    expect(useChatStore.getState().open).toBe(false);
  });

  it('open_ sets open=true regardless of prior state', () => {
    useChatStore.getState().open_();
    expect(useChatStore.getState().open).toBe(true);
    useChatStore.getState().open_();
    expect(useChatStore.getState().open).toBe(true);
  });

  it('close sets open=false', () => {
    useChatStore.setState({ open: true });
    useChatStore.getState().close();
    expect(useChatStore.getState().open).toBe(false);
  });

  it('appendMessage pushes a text message', () => {
    useChatStore.getState().appendMessage({
      id: 'm1',
      role: 'user',
      content: [{ type: 'text', text: 'hi' }],
      ts: 1000,
    });
    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe('m1');
    expect(msgs[0].content[0]).toEqual({ type: 'text', text: 'hi' });
  });

  it('appendMessage supports tool_use and tool_result blocks', () => {
    const { appendMessage } = useChatStore.getState();
    appendMessage({
      id: 'a1',
      role: 'assistant',
      content: [
        { type: 'tool_use', tool_name: 'get_portfolio', tool_input: {}, id: 'tu1' },
      ],
      ts: 2000,
    });
    appendMessage({
      id: 'u1',
      role: 'user',
      content: [{ type: 'tool_result', tool_use_id: 'tu1', output: { equity: 1 } }],
      ts: 2001,
    });
    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[0].content[0].type).toBe('tool_use');
    expect(msgs[1].content[0].type).toBe('tool_result');
  });

  it('setDraft updates draft text', () => {
    useChatStore.getState().setDraft('hello world');
    expect(useChatStore.getState().draft).toBe('hello world');
  });

  it('setPageContext updates route and instrument', () => {
    useChatStore.getState().setPageContext({ route: '/futures', instrument: 'BTC-PERPETUAL' });
    expect(useChatStore.getState().pageContext).toEqual({
      route: '/futures',
      instrument: 'BTC-PERPETUAL',
    });
  });

  it('setPageContext clears instrument when omitted', () => {
    useChatStore.getState().setPageContext({ route: '/futures', instrument: 'BTC-PERPETUAL' });
    useChatStore.getState().setPageContext({ route: '/options' });
    expect(useChatStore.getState().pageContext.instrument).toBeUndefined();
  });

  it('clearMessages empties the history and resets error', () => {
    useChatStore.getState().appendMessage({
      id: 'm1',
      role: 'user',
      content: [{ type: 'text', text: 'x' }],
      ts: 0,
    });
    useChatStore.setState({ error: 'something failed' });
    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(useChatStore.getState().error).toBeNull();
  });

  it('persist partializes only open and messages (not draft / tools)', () => {
    useChatStore.setState({
      open: true,
      messages: [{ id: 'm', role: 'user', content: [{ type: 'text', text: 't' }], ts: 0 }],
      draft: 'unsaved',
      tools: [{ name: 'foo' }],
    });
    const raw = localStorage.getItem('chat-store');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.state.open).toBe(true);
    expect(parsed.state.messages).toHaveLength(1);
    expect(parsed.state.draft).toBeUndefined();
    expect(parsed.state.tools).toBeUndefined();
  });

  it('persist version is set to 1', () => {
    useChatStore.setState({ open: true });
    const raw = localStorage.getItem('chat-store');
    const parsed = JSON.parse(raw!);
    expect(parsed.version).toBe(1);
  });

  it('persist excludes loading and error', () => {
    useChatStore.setState({ open: true, loading: true, error: 'oops' });
    const raw = localStorage.getItem('chat-store');
    const parsed = JSON.parse(raw!);
    expect(parsed.state.loading).toBeUndefined();
    expect(parsed.state.error).toBeUndefined();
  });
});

describe('useChatStore.sendMessage', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('does nothing for empty input', async () => {
    await useChatStore.getState().sendMessage('   ');
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it('appends user message and applies streaming events', async () => {
    // Mock fetch returning a streaming SSE response
    const sseBody =
      'event: text_delta\ndata: {"delta":"Hi"}\n\n' +
      'event: text_delta\ndata: {"delta":" there"}\n\n' +
      'event: done\ndata: {"finish_reason":"stop"}\n\n';
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(sseBody));
        c.close();
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    );

    await useChatStore.getState().sendMessage('hello');

    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[0].role).toBe('user');
    expect(msgs[0].content[0]).toEqual({ type: 'text', text: 'hello' });
    expect(msgs[1].role).toBe('assistant');
    const assistantText = msgs[1].content
      .filter((b) => b.type === 'text')
      .map((b) => (b.type === 'text' ? b.text : ''))
      .join('');
    expect(assistantText).toBe('Hi there');
    expect(useChatStore.getState().loading).toBe(false);
    vi.restoreAllMocks();
  });

  it('records tool_use blocks during streaming', async () => {
    const sseBody =
      'event: tool_use_start\ndata: {"id":"tu1","name":"get_portfolio"}\n\n' +
      'event: tool_use_end\ndata: {"id":"tu1","input":{"currency":"BTC"}}\n\n' +
      'event: tool_result\ndata: {"tool_use_id":"tu1","output":{"equity":428},"is_error":false}\n\n' +
      'event: text_delta\ndata: {"delta":"Equity is $428."}\n\n' +
      'event: done\ndata: {"finish_reason":"stop"}\n\n';
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(sseBody));
        c.close();
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    );

    await useChatStore.getState().sendMessage('what is my equity');

    const assistant = useChatStore.getState().messages[1];
    const toolUse = assistant.content.find((b) => b.type === 'tool_use');
    expect(toolUse).toBeTruthy();
    if (toolUse && toolUse.type === 'tool_use') {
      expect(toolUse.tool_name).toBe('get_portfolio');
      expect((toolUse.tool_input as any).currency).toBe('BTC');
      expect(toolUse.status).toBe('success');
    }
    const toolResult = assistant.content.find((b) => b.type === 'tool_result');
    expect(toolResult).toBeTruthy();
    vi.restoreAllMocks();
  });

  it('sets error on SSE error event', async () => {
    const sseBody =
      'event: error\ndata: {"code":"auth_failed","message":"invalid key"}\n\n';
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(sseBody));
        c.close();
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    );

    await useChatStore.getState().sendMessage('hi');
    expect(useChatStore.getState().error).toContain('invalid key');
    expect(useChatStore.getState().loading).toBe(false);
    vi.restoreAllMocks();
  });

  it('sets error on HTTP 503 response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'AI not configured' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      }),
    );

    await useChatStore.getState().sendMessage('hi');
    expect(useChatStore.getState().error).toContain('AI not configured');
    vi.restoreAllMocks();
  });
});
