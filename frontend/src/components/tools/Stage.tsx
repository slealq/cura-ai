'use client';

import { createContext, useEffect, useRef, useState, type ReactNode } from 'react';
import MobileSheet from './MobileSheet';

export const StageControls = createContext<(title: string) => void>(() => {});

interface StageProps {
  tabs?: ReactNode;
  canvas: ReactNode;
  composer: ReactNode;
  settings: ReactNode;
  mobileFeedKey?: number;
  mobileSheets?: Record<string, ReactNode>;
}

export default function Stage({ tabs, canvas, composer, settings, mobileSheets, mobileFeedKey }: StageProps) {
  const feed = useRef<HTMLDivElement>(null);
  const [sheet, setSheet] = useState('');
  const [keyboard, setKeyboard] = useState(0);

  useEffect(() => {
    if (mobileFeedKey != null && window.matchMedia('(max-width: 767px)').matches && feed.current) {
      feed.current.scrollTop = feed.current.scrollHeight;
    }
  }, [mobileFeedKey]);

  useEffect(() => {
    const viewport = window.visualViewport;
    const update = () => setKeyboard(window.matchMedia('(max-width: 767px)').matches && viewport
      ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) : 0);
    update();
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    return () => {
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, []);

  return (
    <StageControls.Provider value={setSheet}>
      <div style={{ paddingBottom: keyboard }} className="tool-stage grid h-full min-h-0 grid-cols-[minmax(0,1fr)_300px] overflow-hidden bg-background max-md:grid-cols-1">
        <div className="flex min-h-0 min-w-0 flex-col">
          {tabs && <div className="hidden shrink-0 items-center px-4 pt-2.5 md:flex">{tabs}</div>}
          <div ref={feed} className="tool-canvas flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto px-4 py-3">
            {canvas}
          </div>
          <div className="shrink-0">{composer}</div>
        </div>
        <aside className="hidden min-h-0 min-w-0 flex-col gap-3 overflow-y-auto border-l border-border p-3.5 text-[13px] md:flex">
          {settings}
        </aside>
      </div>
      {sheet && (
        <MobileSheet title={sheet} onClose={() => setSheet('')}>
          <div className="flex flex-col gap-3 text-sm">{mobileSheets?.[sheet] ?? settings}</div>
        </MobileSheet>
      )}
    </StageControls.Provider>
  );
}
