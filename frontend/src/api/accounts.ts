/**
 * Multi-account REST wrappers.
 *
 * Server contract lives in src/deribit_trading/rest_api.py — see the
 * "Accounts" section. Endpoint IDs (deribit_prod / tibired_prod /
 * deribit_testnet) are returned by GET /accounts as `endpoints`, so the UI
 * doesn't need to hard-code them.
 */

const BASE = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export type EndpointId = 'deribit_prod' | 'tibired_prod' | 'deribit_testnet';

export interface EndpointInfo {
  id: EndpointId;
  label: string;
  is_production: boolean;
}

export interface AccountSummary {
  id: string;
  alias: string;
  endpoint: EndpointId;
  endpoint_label: string;
  is_production: boolean;
  client_id_tail: string;
  /** Last 4 chars of the stored secret so users can tell which key is saved. */
  client_secret_tail?: string;
  /** Never populated by the server — always empty string. Kept for type compat. */
  client_id: string;
  is_active: boolean;
  created_at: number;
  last_used_at: number | null;
}

export interface ListAccountsResponse {
  accounts: AccountSummary[];
  active_id: string | null;
  endpoints: EndpointInfo[];
}

export interface ActiveAccountResponse {
  active: {
    id: string;
    alias: string;
    endpoint: EndpointId;
    endpoint_label: string;
    is_production: boolean;
    client_id_tail: string;
    client_secret_tail?: string;
    created_at: number;
    last_used_at: number | null;
  } | null;
  connected?: boolean;
  authenticated?: boolean;
}

export interface CreateAccountPayload {
  alias: string;
  endpoint: EndpointId;
  client_id: string;
  client_secret: string;
}

export interface CreateAccountResponse {
  id: string;
  alias: string;
  endpoint: EndpointId;
  client_id_tail: string;
}

export interface UpdateAccountPayload {
  alias?: string;
  client_secret?: string;
}

export interface ActivateResponse {
  id: string;
  alias: string;
  endpoint: EndpointId;
  client_id: string;
  connected: boolean;
  authenticated: boolean;
}

export interface TestCredentialsResult {
  ok: boolean;
  stage?: 'connect' | 'authenticate';
  error?: string;
  ws_url?: string;
}

export function listAccounts(): Promise<ListAccountsResponse> {
  return request('/accounts');
}

export function getActiveAccount(): Promise<ActiveAccountResponse> {
  return request('/accounts/active');
}

export function createAccount(
  payload: CreateAccountPayload,
): Promise<CreateAccountResponse> {
  return request('/accounts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateAccount(
  id: string,
  payload: UpdateAccountPayload,
): Promise<{ status: string; id: string }> {
  return request(`/accounts/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteAccount(id: string): Promise<{ status: string; id: string }> {
  return request(`/accounts/${id}`, { method: 'DELETE' });
}

export function activateAccount(id: string): Promise<ActivateResponse> {
  return request(`/accounts/${id}/activate`, { method: 'POST' });
}

export function testCredentials(payload: {
  endpoint: EndpointId;
  client_id: string;
  client_secret: string;
}): Promise<TestCredentialsResult> {
  return request('/accounts/test-credentials', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function testExistingAccount(id: string): Promise<TestCredentialsResult> {
  return request(`/accounts/${id}/test`, { method: 'POST' });
}
