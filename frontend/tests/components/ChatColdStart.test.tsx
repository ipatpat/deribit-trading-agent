import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ChatColdStart from '../../src/components/chat/ChatColdStart';

describe('ChatColdStart', () => {
  const renderWithRouter = () =>
    render(
      <MemoryRouter>
        <ChatColdStart />
      </MemoryRouter>,
    );

  it('renders the configure prompt', () => {
    renderWithRouter();
    expect(screen.getByText(/configure ai/i)).toBeTruthy();
  });

  it('mentions all three required fields', () => {
    renderWithRouter();
    const helper = screen.getByText(/endpoint.*model.*api key/i);
    expect(helper).toBeTruthy();
  });

  it('Open Settings link navigates to /settings#ai-agent', () => {
    renderWithRouter();
    const link = screen.getByRole('link', { name: /open settings/i });
    expect(link.getAttribute('href')).toBe('/settings#ai-agent');
  });
});
