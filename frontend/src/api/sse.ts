/**
 * Parse a Server-Sent Events (SSE) stream from a fetch Response.
 *
 * Yields { event, data } objects per the spec format:
 *   event: <name>
 *   data: <json string>
 *   <blank line>
 *
 * Features:
 * - Handles partial chunks (events split across network reads)
 * - Skips empty events
 * - Returns parsed JSON for `data` (falls back to raw string if not JSON)
 */

export interface SSEMessage {
  event: string;
  data: any;
}

export async function* parseSSEStream(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<SSEMessage, void, void> {
  if (!response.body) {
    throw new Error('Response has no body to stream');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel();
        return;
      }

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Events are separated by `\n\n`. Keep the trailing partial chunk in buffer.
      let sepIdx: number;
      while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);

        const msg = parseSSEMessage(rawEvent);
        if (msg) yield msg;
      }
    }

    // Flush any final partial event in the buffer
    if (buffer.trim()) {
      const msg = parseSSEMessage(buffer);
      if (msg) yield msg;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSSEMessage(raw: string): SSEMessage | null {
  let event = 'message';
  let dataLines: string[] = [];

  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
    // Other fields (id, retry, comments) ignored
  }

  if (dataLines.length === 0) return null;

  const dataStr = dataLines.join('\n');
  let data: any;
  try {
    data = JSON.parse(dataStr);
  } catch {
    data = dataStr; // Fallback: pass raw string
  }

  return { event, data };
}
