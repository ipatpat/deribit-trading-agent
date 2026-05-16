/**
 * AI Agent backend API client.
 *
 * - Settings CRUD (endpoint/model/api_key)
 * - Test connection (minimal 1-token request)
 * - Chat streaming (SSE via fetch + ReadableStream)
 */

import { parseSSEStream, type SSEMessage } from './sse';

export interface AiAgentConfigPublic {
  endpoint: string | null;
  model: string | null;
  api_key_set: boolean;
  /** Last 4 chars of the saved API key, so users can identify it. Empty when unset. */
  api_key_tail?: string;
  env_fallback_available?: boolean;
}

export interface AiAgentConfigInput {
  endpoint: string;
  model: string;
  api_key: string;
}

export interface TestConnectionResult {
  ok: boolean;
  model?: string;
  usage?: { prompt_tokens: number | null; completion_tokens: number | null; total_tokens: number | null };
  code?: string;
  error?: string;
}

export interface ListModelsResult {
  ok: boolean;
  models?: string[];
  code?: string;
  error?: string;
}

export interface ChatRequest {
  messages: Array<{ role: 'user' | 'assistant' | 'system' | 'tool'; content: any; tool_call_id?: string; tool_calls?: any[] }>;
  page_context?: { route: string; instrument?: string };
  write_enabled?: boolean;
}

// ── Settings CRUD ────────────────────────────────────────────────────────────
export async function getAiAgentConfig(): Promise<AiAgentConfigPublic> {
  const resp = await fetch('/api/v1/settings/ai-agent');
  if (!resp.ok) throw new Error(`GET /settings/ai-agent failed: ${resp.status}`);
  return resp.json();
}

export async function setAiAgentConfig(cfg: AiAgentConfigInput): Promise<{ ok: boolean; api_key_set: boolean }> {
  const resp = await fetch('/api/v1/settings/ai-agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`POST /settings/ai-agent failed: ${detail}`);
  }
  return resp.json();
}

export async function deleteAiAgentConfig(): Promise<{ ok: boolean }> {
  const resp = await fetch('/api/v1/settings/ai-agent', { method: 'DELETE' });
  if (!resp.ok) throw new Error(`DELETE /settings/ai-agent failed: ${resp.status}`);
  return resp.json();
}

// ── Test connection ──────────────────────────────────────────────────────────
export async function testAiAgentConnection(cfg: AiAgentConfigInput): Promise<TestConnectionResult> {
  const resp = await fetch('/api/v1/agent/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  if (!resp.ok) {
    return { ok: false, code: 'http_error', error: `HTTP ${resp.status}` };
  }
  return resp.json();
}

// ── List models ──────────────────────────────────────────────────────────────
export async function listAiAgentModels(
  endpoint: string,
  api_key: string,
): Promise<ListModelsResult> {
  const resp = await fetch('/api/v1/agent/list-models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint, api_key }),
  });
  if (!resp.ok) {
    return { ok: false, code: 'http_error', error: `HTTP ${resp.status}` };
  }
  return resp.json();
}

// ── Chat streaming ───────────────────────────────────────────────────────────
export async function* chatStream(
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<SSEMessage, void, void> {
  const resp = await fetch('/api/v1/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });

  if (!resp.ok) {
    let detail = '';
    try {
      detail = (await resp.json()).detail ?? '';
    } catch {
      detail = await resp.text();
    }
    // Yield as a single error event
    yield {
      event: 'error',
      data: { code: resp.status === 503 ? 'not_configured' : 'http_error', message: detail || `HTTP ${resp.status}` },
    };
    return;
  }

  yield* parseSSEStream(resp, signal);
}

// ── Confirmation flow ────────────────────────────────────────────────────────
export async function confirmTool(
  toolCallId: string,
  confirmed: boolean,
  reason?: string,
): Promise<void> {
  const resp = await fetch(`/api/v1/agent/confirm/${encodeURIComponent(toolCallId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed, reason }),
  });
  if (!resp.ok) {
    throw new Error(`POST /agent/confirm failed: HTTP ${resp.status}`);
  }
}
