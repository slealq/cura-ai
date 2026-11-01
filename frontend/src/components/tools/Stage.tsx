import type { ReactNode } from 'react';

interface StageProps {
  tabs?: ReactNode;
  canvas: ReactNode;
  composer: ReactNode;
  settings: ReactNode;
}

export default function Stage({ tabs, canvas, composer, settings }: StageProps) {
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_300px] overflow-hidden bg-background max-sm:grid-cols-1">
      <div className="flex min-h-0 min-w-0 flex-col">
        {tabs && <div className="flex shrink-0 items-center px-4 pt-2.5">{tabs}</div>}
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto px-4 py-3">
          {canvas}
        </div>
        <div className="shrink-0">{composer}</div>
      </div>
      <aside className="flex min-h-0 min-w-0 flex-col gap-3 overflow-y-auto border-l border-border p-3.5 text-[13px] max-sm:max-h-[40vh] max-sm:border-t">
        {settings}
      </aside>
    </div>
  );
}
