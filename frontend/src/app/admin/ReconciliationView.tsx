'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ZAxis, Legend,
} from 'recharts';
import { billingApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { ReconciliationRow, ScatterPoint } from '@/types';

const OPERATION_COLORS: Record<string, string> = {
  tag: '#3b82f6',
  describe: '#8b5cf6',
  embed: '#06b6d4',
  generate: '#f59e0b',
  edit: '#ec4899',
  train: '#ef4444',
  evaluate: '#10b981',
  summarize: '#6366f1',
  expand_prompt: '#f97316',
};

function deltaColor(pct: number): string {
  const abs = Math.abs(pct);
  if (abs < 10) return 'text-green-600 dark:text-green-400';
  if (abs < 30) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

function ScatterTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ScatterPoint }> }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const delta = p.actual_sparks - p.estimated_sparks;
  const deltaPct = p.estimated_sparks > 0 ? ((delta / p.estimated_sparks) * 100).toFixed(1) : '0';
  return (
    <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs space-y-1">
      <div className="font-medium">{p.operation}</div>
      <div className="text-muted-foreground">{p.provider}</div>
      <div>Estimated: {p.estimated_sparks} sparks</div>
      <div>Actual: {p.actual_sparks} sparks</div>
      <div className={delta > 0 ? 'text-red-500' : 'text-green-500'}>
        Delta: {delta > 0 ? '+' : ''}{delta} ({deltaPct}%)
      </div>
    </div>
  );
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

  const { data: scatterData } = useQuery({
    queryKey: ['admin-scatter', filters.operation],
    queryFn: () => billingApi.adminGetScatterData({
      hours: 24,
      operation: filters.operation || undefined,
      limit: 500,
    }),
  });

  // Group scatter points by operation for multi-colored dots
  const scatterByOp: Record<string, ScatterPoint[]> = {};
  if (scatterData?.items) {
    for (const pt of scatterData.items) {
      if (!scatterByOp[pt.operation]) scatterByOp[pt.operation] = [];
      scatterByOp[pt.operation].push(pt);
    }
  }

  // Compute axis max for reference line
  const maxVal = scatterData?.items?.length
    ? Math.max(...scatterData.items.map((p) => Math.max(p.estimated_sparks, p.actual_sparks))) * 1.1
    : 100;

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

      {/* Scatter Plot */}
      {scatterData && scatterData.items.length > 0 && (
        <div className="border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Estimated vs Actual (last 24h)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis
                type="number"
                dataKey="estimated_sparks"
                name="Estimated"
                domain={[0, maxVal]}
                tick={{ fontSize: 11 }}
                label={{ value: 'Estimated Sparks', position: 'insideBottom', offset: -5, fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey="actual_sparks"
                name="Actual"
                domain={[0, maxVal]}
                tick={{ fontSize: 11 }}
                label={{ value: 'Actual Sparks', angle: -90, position: 'insideLeft', fontSize: 11 }}
              />
              <ZAxis range={[30, 30]} />
              <Tooltip content={<ScatterTooltip />} />
              <Legend />
              <ReferenceLine
                segment={[{ x: 0, y: 0 }, { x: maxVal, y: maxVal }]}
                stroke="#888"
                strokeDasharray="5 5"
                label={{ value: 'Perfect', position: 'insideTopLeft', fontSize: 10, fill: '#888' }}
              />
              {Object.entries(scatterByOp).map(([op, points]) => (
                <Scatter
                  key={op}
                  name={op}
                  data={points}
                  fill={OPERATION_COLORS[op] || '#888'}
                  opacity={0.7}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}

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
