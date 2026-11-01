'use client';

import { useEffect, useRef } from 'react';

/** Keep keyboard focus inside a phone sheet and return it to the opener. */
export function useMobileSheet(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open || !window.matchMedia('(max-width: 767px)').matches) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = ref.current;
    const controls = () => Array.from(element?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, select, textarea') ?? []).filter(e => e.getClientRects().length);
    controls()[0]?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close.current(); }
      if (e.key !== 'Tab') return;
      const items = controls();
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    window.addEventListener('keydown', key, true);
    return () => { window.removeEventListener('keydown', key, true); previous?.focus(); };
  }, [open]);
  return ref;
}
