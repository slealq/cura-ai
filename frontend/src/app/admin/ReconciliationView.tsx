'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { billingApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { ReconciliationRow } from '@/types';

function deltaColor(pct: number): string {
  const abs = Math.abs(pct);
  if (abs < 10) return 'text-green-600 dark:text-green-400';
  if (abs < 30) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

export default function ReconciliationView() {
  const [filters, setFilters] = useState<{
    operation?: string;
    provider?: string;
    threshold_pct?: number;
  }>({ threshold_pct: 20 });

  const { data, isLoading } = useQuery({
    queryKey: ['admin-reconciliation', filters],
    queryFn: () => billingApi.adminGetReconciliation({
      operation: filters.operation || undefined,
      provider: filters.provider || undefined,
      threshold_pct: filters.threshold_pct,
    }),
  });

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.operation || ''}
          onChange={(e) => setFilters({ ...filters, operation: e.target.value })}
        >
          <option value="">All operations</option>
          {['tag', 'describe', 'embed', 'generate', 'edit', 'train', 'evaluate', 'summarize', 'expand_prompt'].map((op) => (
            <option key={op} value={op}>{op}</option>
          ))}
        </select>
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.provider || ''}
          onChange={(e) => setFilters({ ...filters, provider: e.target.value })}
        >
          <option value="">All providers</option>
          {['openai', 'anthropic', 'fal'].map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Threshold:</span>
          <input
            type="number"
            className="w-16 px-2 py-1.5 text-sm border rounded-md bg-background"
            value={filters.threshold_pct ?? 20}
            onChange={(e) => setFilters({ ...filters, threshold_pct: Number(e.target.value) })}
            min={0}
            max={100}
          />
          <span className="text-muted-foreground">%</span>
        </label>
      </div>

      {/* Summary */}
      {data && (
        <div className="flex gap-4 text-sm">
          <span className="text-muted-foreground">{data.items.length} operation groups</span>
          {data.threshold_violations > 0 && (
            <span className="text-red-600 dark:text-red-400 font-medium">
              {data.threshold_violations} threshold violation{data.threshold_violations !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left p-2 font-medium">Operation</th>
              <th className="text-left p-2 font-medium">Provider / Model</th>
              <th className="text-right p-2 font-medium"># Decisions</th>
              <th className="text-right p-2 font-medium">Avg Est</th>
              <th className="text-right p-2 font-medium">Avg Actual</th>
              <th className="text-right p-2 font-medium">Delta</th>
              <th className="text-right p-2 font-medium">Delta %</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-8"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr>
            ) : !data?.items?.length ? (
              <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">No reconciliation data</td></tr>
            ) : (
              data.items.map((row: ReconciliationRow, idx: number) => (
                <tr key={idx} className="border-t hover:bg-muted/30">
                  <td className="p-2">{row.operation}</td>
                  <td className="p-2 text-xs">{row.provider}/{row.model.length > 30 ? row.model.slice(0, 30) + '...' : row.model}</td>
                  <td className="p-2 text-right font-mono">{row.total_decisions}</td>
                  <td className="p-2 text-right font-mono">{row.avg_estimated_sparks.toFixed(1)}</td>
                  <td className="p-2 text-right font-mono">{row.avg_actual_sparks.toFixed(1)}</td>
                  <td className={cn('p-2 text-right font-mono', deltaColor(row.avg_delta_pct))}>
                    {row.avg_delta > 0 ? '+' : ''}{row.avg_delta.toFixed(1)}
                  </td>
                  <td className={cn('p-2 text-right font-mono font-medium', deltaColor(row.avg_delta_pct))}>
                    {row.avg_delta_pct > 0 ? '+' : ''}{row.avg_delta_pct.toFixed(1)}%
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
