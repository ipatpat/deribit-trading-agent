interface KeyEvent {
  key: string;
  shiftKey: boolean;
  nativeEvent: { isComposing: boolean };
  keyCode: number;
}

/**
 * Decide whether an Enter keydown should trigger send.
 *
 * Returns true only when Enter is pressed without Shift, AND the user is
 * NOT in an IME composition session. `isComposing` is the W3C standard
 * property (supported in Chrome/Safari/Firefox); `keyCode === 229` is the
 * legacy IME-composing magic value for older browsers (notably IE / old
 * Safari WebKit).
 */
export function shouldSendOnEnter(e: KeyEvent): boolean {
  return (
    e.key === 'Enter'
    && !e.shiftKey
    && !e.nativeEvent.isComposing
    && e.keyCode !== 229
  );
}
