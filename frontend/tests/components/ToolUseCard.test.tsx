import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ToolUseCard from '../../src/components/chat/ToolUseCard';

describe('ToolUseCard', () => {
  it('renders tool name and pending spinner when status=pending', () => {
    render(<ToolUseCard name="get_portfolio" input={{ currency: 'BTC' }} status="pending" />);
    expect(screen.getByText('get_portfolio')).toBeTruthy();
    // Loader2 has class animate-spin
    const spinner = document.querySelector('.animate-spin');
    expect(spinner).toBeTruthy();
  });

  it('renders args preview', () => {
    render(<ToolUseCard name="get_ticker" input={{ instrument_name: 'BTC-PERPETUAL' }} status="success" result={{ price: 80000 }} />);
    expect(screen.getByText(/instrument_name/)).toBeTruthy();
  });

  it('expands result on click', () => {
    render(<ToolUseCard name="get_portfolio" input={{}} status="success" result={{ equity: 428, balance: 100 }} />);
    const button = screen.getByRole('button');
    fireEvent.click(button);
    // Full JSON should now be visible
    expect(screen.getByText(/"equity": 428/)).toBeTruthy();
  });

  it('shows error styling when isError', () => {
    render(<ToolUseCard name="get_ticker" input={{}} status="error" result="Tool failed" isError={true} />);
    // Look for an X icon (lucide X has lucide-x class) — fallback to checking the text-loss class
    const errorElements = document.querySelectorAll('.text-loss');
    expect(errorElements.length).toBeGreaterThan(0);
  });
});
