import { PIPELINE_STEPS, STATUS_RANK } from '@/lib/pipeline';
import { cn } from '@/lib/utils';

interface PipelineProgressProps {
  status: string;
  variant?: 'compact' | 'full';
  staleSteps?: string[];
}

export default function PipelineProgress({
  status,
  variant = 'compact',
  staleSteps,
}: PipelineProgressProps) {
  const isFailed = status === 'failed';
  const currentRank = STATUS_RANK[status] ?? -1;

  if (variant === 'compact') {
    return (
      <div className="flex items-center gap-1">
        {PIPELINE_STEPS.map((step) => {
          const stepRank = STATUS_RANK[step.key];
          const isCompleted = !isFailed && currentRank >= stepRank;
          const isCurrent = !isFailed && status === step.key;
          const isStale = staleSteps?.includes(step.key);

          return (
            <span
              key={step.key}
              title={isStale ? `${step.label} (stale)` : step.label}
              className={cn(
                'rounded-full transition-all',
                isFailed
                  ? 'h-2 w-2 bg-red-400/60'
                  : isStale
                    ? 'h-2 w-2 bg-yellow-400'
                    : isCompleted
                      ? cn('h-2 w-2', step.color)
                      : 'h-1.5 w-1.5 bg-white/30',
                isCurrent && 'h-2.5 w-2.5 ring-2 ring-white/50'
              )}
            />
          );
        })}
      </div>
    );
  }

  // Full variant
  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STEPS.map((step, i) => {
        const stepRank = STATUS_RANK[step.key];
        const isCompleted = !isFailed && currentRank >= stepRank;
        const isCurrent = !isFailed && status === step.key;
        const isStale = staleSteps?.includes(step.key);

        return (
          <div key={step.key} className="flex items-center gap-1">
            {i > 0 && (
              <div
                className={cn(
                  'h-px w-4',
                  isCompleted || isStale ? 'bg-border' : 'bg-border/40'
                )}
              />
            )}
            <div className="flex flex-col items-center gap-1">
              <span
                className={cn(
                  'rounded-full transition-all',
                  isFailed
                    ? 'h-2.5 w-2.5 bg-red-400/60'
                    : isStale
                      ? 'h-2.5 w-2.5 bg-yellow-400'
                      : isCompleted
                        ? cn('h-2.5 w-2.5', step.color)
                        : 'h-2 w-2 bg-muted-foreground/30',
                  isCurrent && 'h-3 w-3 ring-2 ring-offset-1 ring-offset-white ring-current'
                )}
                style={isCurrent ? { color: 'var(--tw-shadow-color, currentColor)' } : undefined}
              />
              <span
                className={cn(
                  'text-[10px] leading-none',
                  isStale
                    ? 'text-yellow-600 font-medium'
                    : isCompleted
                      ? 'text-foreground font-medium'
                      : 'text-muted-foreground'
                )}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
      {isFailed && (
        <div className="flex items-center gap-1 ml-1">
          <span className="text-[10px] leading-none text-red-500 font-medium">
            Failed
          </span>
        </div>
      )}
    </div>
  );
}
