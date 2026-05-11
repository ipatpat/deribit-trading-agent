import { describe, it, expect } from 'vitest';
import { parseSSEStream } from '../../src/api/sse';

function _streamFromChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

async function _collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const v of gen) out.push(v);
  return out;
}

describe('parseSSEStream', () => {
  it('parses a single event', async () => {
    const resp = _streamFromChunks([
      'event: text_delta\ndata: {"delta":"hi"}\n\n',
    ]);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toEqual([{ event: 'text_delta', data: { delta: 'hi' } }]);
  });

  it('parses multiple events in one chunk', async () => {
    const resp = _streamFromChunks([
      'event: text_delta\ndata: {"delta":"a"}\n\nevent: text_delta\ndata: {"delta":"b"}\n\n',
    ]);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toHaveLength(2);
    expect(events[0].data.delta).toBe('a');
    expect(events[1].data.delta).toBe('b');
  });

  it('handles event split across chunks', async () => {
    const resp = _streamFromChunks([
      'event: text_delta\ndata: {"del',
      'ta":"split"}\n\n',
    ]);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toEqual([{ event: 'text_delta', data: { delta: 'split' } }]);
  });

  it('skips empty events', async () => {
    const resp = _streamFromChunks(['\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n']);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('done');
  });

  it('falls back to raw string for non-JSON data', async () => {
    const resp = _streamFromChunks(['event: ping\ndata: not-json-payload\n\n']);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toEqual([{ event: 'ping', data: 'not-json-payload' }]);
  });

  it('uses "message" as default event type when not specified', async () => {
    const resp = _streamFromChunks(['data: {"x":1}\n\n']);
    const events = await _collect(parseSSEStream(resp));
    expect(events[0].event).toBe('message');
  });

  it('emits final partial event on stream close', async () => {
    // No trailing \n\n — flush via finally
    const resp = _streamFromChunks(['event: done\ndata: {"finish_reason":"stop"}']);
    const events = await _collect(parseSSEStream(resp));
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('done');
  });

  it('handles full agent loop event sequence', async () => {
    const resp = _streamFromChunks([
      'event: text_delta\ndata: {"delta":"Looking..."}\n\n',
      'event: tool_use_start\ndata: {"id":"tu1","name":"get_portfolio"}\n\n',
      'event: tool_use_end\ndata: {"id":"tu1","input":{"currency":"BTC"}}\n\n',
      'event: tool_result\ndata: {"tool_use_id":"tu1","output":{"equity":428},"is_error":false}\n\n',
      'event: text_delta\ndata: {"delta":"Your equity is $428."}\n\n',
      'event: done\ndata: {"finish_reason":"stop"}\n\n',
    ]);
    const events = await _collect(parseSSEStream(resp));
    expect(events.map((e) => e.event)).toEqual([
      'text_delta', 'tool_use_start', 'tool_use_end', 'tool_result', 'text_delta', 'done',
    ]);
  });
});
