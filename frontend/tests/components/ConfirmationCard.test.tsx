import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import ConfirmationCard from '../../src/components/chat/ConfirmationCard';
import { useChatStore } from '../../src/stores/chat';

describe('ConfirmationCard', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useChatStore.setState({
      open: true, messages: [], draft: '', pageContext: { route: '/' },
      tools: [], writeEnabled: true, loading: false, error: null,
    });
    (global as any).fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
  });

  it('renders summary + tool name + Confirm/Cancel buttons', () => {
    render(
      <ConfirmationCard
        toolCallId="tc_1"
        toolName="place_order"
        toolInput={{ instrument_name: 'BTC-PERPETUAL', direction: 'buy' }}
        summary="BUY BTC-PERPETUAL · 1"
      />
    );
    expect(screen.getByText(/place_order/i)).toBeTruthy();
    expect(screen.getByText(/BUY BTC-PERPETUAL/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /confirm trade/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeTruthy();
  });

  it('Confirm click posts confirmed=true to backend', async () => {
    render(
      <ConfirmationCard
        toolCallId="tc_2"
        toolName="place_order"
        toolInput={{}}
        summary="x"
      />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /confirm trade/i }));
    });
    expect((global as any).fetch).toHaveBeenCalled();
    const [url, opts] = (global as any).fetch.mock.calls[0];
    expect(url).toMatch(/\/agent\/confirm\/tc_2/);
    expect(JSON.parse(opts.body).confirmed).toBe(true);
  });

  it('Cancel click posts confirmed=false', async () => {
    render(
      <ConfirmationCard
        toolCallId="tc_3"
        toolName="cancel_order"
        toolInput={{}}
        summary="x"
      />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    });
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.confirmed).toBe(false);
  });

  it('30s timeout auto-cancels with ui_timeout reason', async () => {
    render(
      <ConfirmationCard
        toolCallId="tc_4"
        toolName="place_order"
        toolInput={{}}
        summary="x"
      />
    );
    await act(async () => {
      vi.advanceTimersByTime(31_000);
    });
    expect((global as any).fetch).toHaveBeenCalled();
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.confirmed).toBe(false);
    expect(body.reason).toBe('ui_timeout');
  });

  it('second click after resolved does not fire another fetch', async () => {
    render(
      <ConfirmationCard
        toolCallId="tc_5"
        toolName="place_order"
        toolInput={{}}
        summary="x"
      />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /confirm trade/i }));
    });
    const firstCount = (global as any).fetch.mock.calls.length;
    // Buttons are disabled; click again — should be a no-op.
    fireEvent.click(screen.getByRole('button', { name: /submitting/i }));
    expect((global as any).fetch.mock.calls.length).toBe(firstCount);
  });
});
