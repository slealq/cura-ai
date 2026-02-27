'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, AlertTriangle, CheckCircle } from 'lucide-react';
import { billingApi } from '@/lib/api';
import { formatDateCompact } from '@/lib/utils';
import type { AnomalyEntry } from '@/types';

export default function AnomaliesView() {
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

  return (
    <div className="space-y-4">
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
          <option value="catalog_miss">Catalog Miss</option>
          <option value="estimation_delta">Estimation Delta</option>
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
                <tr key={a.id} className="border-t hover:bg-muted/30">
                  <td className="p-2">
                    <span className="flex items-center gap-1">
                      {a.anomaly_type === 'catalog_miss' ? (
                        <AlertTriangle className="h-3.5 w-3.5 text-yellow-500" />
                      ) : (
                        <AlertTriangle className="h-3.5 w-3.5 text-orange-500" />
                      )}
                      {a.anomaly_type}
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
                  <td className="p-2 text-right">
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
