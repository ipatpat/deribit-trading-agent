import { describe, it, expect } from 'vitest';
import { shouldSendOnEnter } from '../../src/components/chat/keyboardUtils';

const evt = (overrides: Partial<{
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
  keyCode: number;
}> = {}) => ({
  key: overrides.key ?? 'Enter',
  shiftKey: overrides.shiftKey ?? false,
  nativeEvent: { isComposing: overrides.isComposing ?? false },
  keyCode: overrides.keyCode ?? 13,
});

describe('shouldSendOnEnter (IME guard)', () => {
  it('plain Enter sends', () => {
    expect(shouldSendOnEnter(evt())).toBe(true);
  });

  it('Shift+Enter does NOT send', () => {
    expect(shouldSendOnEnter(evt({ shiftKey: true }))).toBe(false);
  });

  it('non-Enter keys do NOT send', () => {
    expect(shouldSendOnEnter(evt({ key: 'a' }))).toBe(false);
  });

  it('IME composing Enter (isComposing=true) does NOT send', () => {
    expect(shouldSendOnEnter(evt({ isComposing: true }))).toBe(false);
  });

  it('legacy IME composing Enter (keyCode=229) does NOT send', () => {
    expect(shouldSendOnEnter(evt({ keyCode: 229 }))).toBe(false);
  });

  it('both flags simultaneously — still does NOT send', () => {
    expect(shouldSendOnEnter(evt({ isComposing: true, keyCode: 229 }))).toBe(false);
  });
});
