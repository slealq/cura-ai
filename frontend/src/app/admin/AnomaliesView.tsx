'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, AlertTriangle, CheckCircle, ExternalLink } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { billingApi } from '@/lib/api';
import { formatDateCompact } from '@/lib/utils';
import type { AnomalyEntry } from '@/types';

const ANOMALY_TYPES = [
  'catalog_miss',
  'estimation_delta',
  'stale_decision',
  'missing_actual_reconcile',
  'estimate_drift',
  'reservation_leak',
] as const;

const ANOMALY_TYPE_COLORS: Record<string, string> = {
  catalog_miss: '#f59e0b',
  estimation_delta: '#f97316',
  stale_decision: '#ef4444',
  missing_actual_reconcile: '#8b5cf6',
  estimate_drift: '#ec4899',
  reservation_leak: '#06b6d4',
};

interface AnomaliesViewProps {
  onViewTrace?: (traceId: string) => void;
}

function TrendTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs space-y-1">
      <div className="font-medium">{label ? new Date(label).toLocaleString() : ''}</div>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span>{entry.name}: {entry.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function AnomaliesView({ onViewTrace }: AnomaliesViewProps) {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<{
    anomaly_type?: string;
    resolved?: boolean | undefined;
    provider?: string;
  }>({ resolved: false });
  const limit = 50;

  const { data: summary } = useQuery({
    queryKey: ['admin-anomaly-summary'],
    queryFn: () => billingApi.adminGetAnomalySummary(),
  });

  const { data, isLoading } = useQuery({
    queryKey: ['admin-anomalies', page, filters],
    queryFn: () => billingApi.adminGetAnomalies({
      skip: page * limit,
      limit,
      anomaly_type: filters.anomaly_type || undefined,
      resolved: filters.resolved,
      provider: filters.provider || undefined,
    }),
  });

  const { data: trendData } = useQuery({
    queryKey: ['admin-anomaly-trend'],
    queryFn: () => billingApi.adminGetAnomalyTrend(168),
  });

  const resolveMutation = useMutation({
    mutationFn: (id: number) => billingApi.adminResolveAnomaly(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-anomalies'] });
      queryClient.invalidateQueries({ queryKey: ['admin-anomaly-summary'] });
    },
  });

  const createCatalogMutation = useMutation({
    mutationFn: (id: number) => billingApi.adminCreateCatalogFromAnomaly(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-anomalies'] });
      queryClient.invalidateQueries({ queryKey: ['admin-anomaly-summary'] });
    },
  });

  // Flatten trend data for stacked bar chart
  const trendChartData = trendData?.items?.map((bucket) => ({
    hour: new Date(bucket.hour).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: 'numeric' }),
    ...bucket.by_type,
    total: bucket.total,
  })) ?? [];

  // Get all anomaly type keys present in trend data
  const trendTypes = new Set<string>();
  trendData?.items?.forEach((b) => Object.keys(b.by_type).forEach((t) => trendTypes.add(t)));

  const handleRowClick = (anomaly: AnomalyEntry) => {
    if (!onViewTrace) return;
    const traceId = anomaly.detail?.trace_id as string | undefined;
    if (traceId) {
      onViewTrace(traceId);
    }
  };

  return (
    <div className="space-y-4">
      {/* Trend chart */}
      {trendChartData.length > 0 && (
        <div className="border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Anomaly Trend (last 7 days)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={trendChartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="hour" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip content={<TrendTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {Array.from(trendTypes).map((type) => (
                <Bar
                  key={type}
                  dataKey={type}
                  stackId="anomalies"
                  fill={ANOMALY_TYPE_COLORS[type] || '#888'}
                  name={type}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <div className="border rounded-lg p-3 text-center">
            <div className="text-2xl font-bold">{summary.total_unresolved}</div>
            <div className="text-xs text-muted-foreground">Unresolved</div>
          </div>
          <div className="border rounded-lg p-3 text-center">
            <div className="text-2xl font-bold">{summary.groups.filter(g => g.anomaly_type === 'catalog_miss').reduce((s, g) => s + g.count, 0)}</div>
            <div className="text-xs text-muted-foreground">Catalog Misses</div>
          </div>
          <div className="border rounded-lg p-3 text-center">
            <div className="text-2xl font-bold">{summary.last_24h_count}</div>
            <div className="text-xs text-muted-foreground">Last 24h</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.anomaly_type || ''}
          onChange={(e) => { setFilters({ ...filters, anomaly_type: e.target.value }); setPage(0); }}
        >
          <option value="">All types</option>
          {ANOMALY_TYPES.map((type) => (
            <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>
          ))}
        </select>
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.resolved === undefined ? '' : filters.resolved ? 'true' : 'false'}
          onChange={(e) => {
            const val = e.target.value;
            setFilters({ ...filters, resolved: val === '' ? undefined : val === 'true' });
            setPage(0);
          }}
        >
          <option value="">All</option>
          <option value="false">Unresolved</option>
          <option value="true">Resolved</option>
        </select>
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.provider || ''}
          onChange={(e) => { setFilters({ ...filters, provider: e.target.value }); setPage(0); }}
        >
          <option value="">All providers</option>
          {['openai', 'anthropic', 'fal'].map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left p-2 font-medium">Type</th>
              <th className="text-left p-2 font-medium">Provider / Model</th>
              <th className="text-left p-2 font-medium">Operation</th>
              <th className="text-left p-2 font-medium">Status</th>
              <th className="text-left p-2 font-medium">Created</th>
              <th className="text-right p-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-8"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr>
            ) : !data?.items?.length ? (
              <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">No anomalies found</td></tr>
            ) : (
              data.items.map((a: AnomalyEntry) => (
                <tr
                  key={a.id}
                  className={`border-t hover:bg-muted/30 ${onViewTrace && a.detail?.trace_id ? 'cursor-pointer' : ''}`}
                  onClick={() => handleRowClick(a)}
                >
                  <td className="p-2">
                    <span className="flex items-center gap-1">
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ backgroundColor: ANOMALY_TYPE_COLORS[a.anomaly_type] || '#888' }}
                      />
                      {a.anomaly_type}
                      {onViewTrace && !!a.detail?.trace_id && (
                        <ExternalLink className="h-3 w-3 text-muted-foreground" />
                      )}
                    </span>
                  </td>
                  <td className="p-2 text-xs">{a.provider}/{a.model ? (a.model.length > 25 ? a.model.slice(0, 25) + '...' : a.model) : '-'}</td>
                  <td className="p-2">{a.operation || '-'}</td>
                  <td className="p-2">
                    {a.resolved ? (
                      <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                        <CheckCircle className="h-3.5 w-3.5" /> Resolved
                      </span>
                    ) : (
                      <span className="text-yellow-600 dark:text-yellow-400">Open</span>
                    )}
                  </td>
                  <td className="p-2 text-xs text-muted-foreground">{formatDateCompact(a.created_at)}</td>
                  <td className="p-2 text-right" onClick={(e) => e.stopPropagation()}>
                    {!a.resolved && (
                      <div className="flex gap-1 justify-end">
                        <button
                          className="px-2 py-1 text-xs border rounded hover:bg-muted disabled:opacity-50"
                          disabled={resolveMutation.isPending}
                          onClick={() => resolveMutation.mutate(a.id)}
                        >
                          Resolve
                        </button>
                        {a.anomaly_type === 'catalog_miss' && (
                          <button
                            className="px-2 py-1 text-xs border rounded hover:bg-muted disabled:opacity-50"
                            disabled={createCatalogMutation.isPending}
                            onClick={() => createCatalogMutation.mutate(a.id)}
                          >
                            Create Entry
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total > limit && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">{data.total} total</span>
          <div className="flex gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
              className="px-3 py-1 border rounded-md disabled:opacity-50"
            >
              Prev
            </button>
            <span className="px-2 py-1">Page {page + 1} of {Math.ceil(data.total / limit)}</span>
            <button
              disabled={(page + 1) * limit >= data.total}
              onClick={() => setPage(page + 1)}
              className="px-3 py-1 border rounded-md disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
