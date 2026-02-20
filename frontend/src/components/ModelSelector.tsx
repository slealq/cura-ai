'use client';

import { cn } from '@/lib/utils';

export interface ModelOption {
  value: string;
  label: string;
  provider?: string;
}

interface ModelSelectorProps {
  models: ModelOption[];
  value: string;
  onChange: (value: string, provider?: string) => void;
  className?: string;
  size?: 'sm' | 'md';
  label?: string;
}

export default function ModelSelector({
  models,
  value,
  onChange,
  className,
  size = 'md',
  label,
}: ModelSelectorProps) {
  return (
    <div className={className}>
      {label && (
        <label className="block text-sm font-medium text-foreground mb-1.5">
          {label}
        </label>
      )}
      <div className="flex flex-wrap gap-1.5">
        {models.map((model) => (
          <button
            key={model.value}
            type="button"
            onClick={() => onChange(model.value, model.provider)}
            className={cn(
              'rounded-full font-medium transition-all duration-150 cursor-pointer',
              size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1.5 text-sm',
              value === model.value
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'border border-border text-muted-foreground hover:bg-muted hover:text-foreground'
            )}
          >
            {model.label}
          </button>
        ))}
      </div>
    </div>
  );
}
