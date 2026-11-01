'use client';

import { useContext, useState, type ReactNode } from 'react';
import { StageControls } from './Stage';
import MobileSheet from './MobileSheet';

export default function SheetButton({ title, children, label }: { title: string; label?: string; children?: ReactNode }) {
  const openSettings = useContext(StageControls);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="min-h-10 rounded-md border border-input px-3 text-sm md:hidden" onClick={() => children ? setOpen(true) : openSettings(title)}>{label || title}</button>
      {open && <MobileSheet title={title} onClose={() => setOpen(false)}>{children}</MobileSheet>}
    </>
  );
}
