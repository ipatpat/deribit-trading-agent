import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatFab from '../../src/components/chat/ChatFab';
import { useChatStore } from '../../src/stores/chat';

const reset = () =>
  useChatStore.setState({
    open: false,
    messages: [],
    draft: '',
    pageContext: { route: '/' },
    tools: [],
  });

describe('ChatFab', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('renders the FAB when chat is closed', () => {
    render(<ChatFab />);
    expect(screen.getByLabelText('Open AI assistant')).toBeTruthy();
  });

  it('returns null when chat is open', () => {
    useChatStore.setState({ open: true });
    const { container } = render(<ChatFab />);
    expect(container.firstChild).toBeNull();
  });

  it('clicking the FAB toggles the chat open', () => {
    render(<ChatFab />);
    expect(useChatStore.getState().open).toBe(false);
    fireEvent.click(screen.getByLabelText('Open AI assistant'));
    expect(useChatStore.getState().open).toBe(true);
  });
});
