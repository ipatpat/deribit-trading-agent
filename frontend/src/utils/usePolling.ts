import { useEffect, useRef } from 'react';

/**
 * Calls `fn` immediately, then every `intervalMs` milliseconds.
 * Stops when intervalMs is null or component unmounts.
 */
export function usePolling(fn: () => void, intervalMs: number | null) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    fnRef.current(); // initial call
    if (intervalMs == null || intervalMs <= 0) return;

    const id = setInterval(() => fnRef.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
