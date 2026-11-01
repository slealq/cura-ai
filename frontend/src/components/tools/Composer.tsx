'use client';

import { useContext, type ReactNode } from 'react';
import { StageControls } from './Stage';

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onApply: () => void;
  disabled: boolean;
  model?: string;
  count: number;
  cost?: number;
  warning?: string;
  chips?: ReactNode;
  mobileChips?: ReactNode;
  mobileHidden?: boolean;
  placeholder?: string;
  action?: string;
}

export default function Composer({ value, onChange, onApply, disabled, model, count, cost, warning, chips, mobileChips, mobileHidden, placeholder = 'What should change?', action = 'Apply' }: ComposerProps) {
  const openSettings = useContext(StageControls);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) onApply();
      }}
      className={`${mobileHidden ? 'hidden md:flex' : 'flex'} tool-composer mx-4 mb-3.5 flex-col gap-2 rounded-[10px] border border-input bg-background px-2.5 py-2 shadow-[0_2px_10px_hsl(0_0%_0%/0.06)]`}
    >
      <textarea
        aria-label={placeholder}
        placeholder={placeholder}
        rows={2}
        onKeyDown={event => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            if (!disabled) onApply();
          }
        }}
        maxLength={8000}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-[42px] w-full resize-none border-0 bg-transparent text-sm leading-snug outline-none"
      />
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <div className="flex gap-1.5 md:hidden">
          {mobileChips ?? <>
          <button type="button" className="min-h-10 rounded-md border px-2" onClick={() => openSettings('Model')}>{model || 'Model'}</button>
          <button type="button" className="min-h-10 rounded-md border px-2" onClick={() => openSettings('Settings')}>{count} {count === 1 ? 'result' : 'results'} · Settings</button>
          </>}
        </div>
        <div className="hidden md:contents">
        {chips ?? (
          <>
            <span className="rounded-md border border-border px-2 py-1 text-muted-foreground">{model}</span>
            <span className="rounded-md border border-border px-2 py-1 text-muted-foreground">
              {count} {count === 1 ? 'result' : 'results'}
            </span>
          </>
        )}
        </div>
        {warning && <span role="status" className="text-amber-700 dark:text-amber-400">{warning}</span>}
        <span className="flex-1" />
        <span className="hidden font-mono text-muted-foreground md:inline">
          {cost != null ? `about ${cost} sparks` : 'Price unavailable'}
        </span>
        <button disabled={disabled} className="rounded-md bg-primary px-3.5 py-1.5 font-medium text-primary-foreground disabled:opacity-50">
          {action}
          <small className="block font-mono md:hidden">{cost != null ? `${cost} sparks` : 'Price unavailable'}</small>
        </button>
      </div>
    </form>
  );
}
