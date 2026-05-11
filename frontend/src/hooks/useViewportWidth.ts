import { useEffect, useState } from 'react';

/**
 * Subscribes to window resize and returns current innerWidth.
 * SSR-safe: returns Infinity before mount.
 */
export function useViewportWidth(): number {
  const [width, setWidth] = useState<number>(() =>
    typeof window === 'undefined' ? Infinity : window.innerWidth,
  );

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return width;
}

/**
 * Returns true when viewport is narrow (< 1440px).
 * Used to trigger chat-compact mode when chat sidebar opens on smaller screens.
 */
export function useIsNarrowViewport(): boolean {
  return useViewportWidth() < 1440;
}
