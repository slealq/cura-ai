interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onApply: () => void;
  disabled: boolean;
  model?: string;
  count: number;
  cost?: number;
  warning?: string;
}

export default function Composer({ value, onChange, onApply, disabled, model, count, cost, warning }: ComposerProps) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onApply();
      }}
      className="mx-4 mb-3.5 flex flex-col gap-2 rounded-[10px] border border-input bg-background px-2.5 py-2 shadow-[0_2px_10px_hsl(0_0%_0%/0.06)]"
    >
      <textarea
        aria-label="What should change?"
        placeholder="What should change?"
        rows={2}
        maxLength={8000}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-[42px] w-full resize-none border-0 bg-transparent text-sm leading-snug outline-none"
      />
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="rounded-md border border-border px-2 py-1 text-muted-foreground">{model}</span>
        <span className="rounded-md border border-border px-2 py-1 text-muted-foreground">
          {count} {count === 1 ? 'result' : 'results'}
        </span>
        {warning && <span role="status" className="text-amber-700 dark:text-amber-400">{warning}</span>}
        <span className="flex-1" />
        <span className="font-mono text-muted-foreground">
          {cost != null ? `about ${cost} sparks` : 'Price unavailable'}
        </span>
        <button disabled={disabled} className="rounded-md bg-primary px-3.5 py-1.5 font-medium text-primary-foreground disabled:opacity-50">
          Apply
        </button>
      </div>
    </form>
  );
}
