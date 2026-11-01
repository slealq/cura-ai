'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useMobileSheet } from '@/hooks/useMobileSheet';

export default function MobileSheet({ title, onClose, children }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useMobileSheet(true, onClose);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const dismiss = () => close.current();
    window.addEventListener('mobile-close-sheets', dismiss);
    return () => window.removeEventListener('mobile-close-sheets', dismiss);
  }, []);
  return createPortal(
    <div className="fixed inset-0 z-[70] bg-black/50 md:hidden" onClick={onClose}>
      <section ref={ref} role="dialog" aria-modal="true" aria-label={title} className="mobile-sheet absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rounded-t-2xl bg-background p-4 pb-[max(16px,env(safe-area-inset-bottom))] space-y-3" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">{title}</h2>
          <button className="min-h-10 px-2" onClick={onClose}>Done</button>
        </div>
        {children}
      </section>
    </div>, document.body,
  );
}
