'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Search, ChevronDown, ChevronRight, X } from 'lucide-react';
import { billingApi } from '@/lib/api';
import { cn, formatDateCompact } from '@/lib/utils';
import type { CostDecisionEntry, TraceResponse } from '@/types';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  executed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  charged: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  cancelled: 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', STATUS_COLORS[status] || 'bg-gray-100 text-gray-800')}>
      {status}
    </span>
  );
}

function truncate(str: string | null, len: number): string {
  if (!str) return '-';
  return str.length > len ? str.slice(0, len) + '...' : str;
}

export default function OperationsMonitor() {
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<{
    trace_id?: string;
    job_id?: string;
    user_id?: string;
    image_id?: string;
    operation?: string;
    status?: string;
  }>({});
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const limit = 50;

  const { data, isLoading } = useQuery({
    queryKey: ['admin-operations', page, filters],
    queryFn: () =>
      billingApi.adminSearchOperations({
        skip: page * limit,
        limit,
        trace_id: filters.trace_id || undefined,
        job_id: filters.job_id ? parseInt(filters.job_id) : undefined,
        user_id: filters.user_id ? parseInt(filters.user_id) : undefined,
        image_id: filters.image_id ? parseInt(filters.image_id) : undefined,
        operation: filters.operation || undefined,
        status: filters.status || undefined,
      }),
  });

  const { data: traceData, isLoading: traceLoading } = useQuery({
    queryKey: ['admin-trace', selectedTraceId],
    queryFn: () => billingApi.adminGetTrace(selectedTraceId!),
    enabled: !!selectedTraceId,
  });

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">Operations Monitor</h2>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative">
          <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Trace ID"
            className="pl-8 pr-2 py-1.5 text-sm border rounded-md w-40 bg-background"
            value={filters.trace_id || ''}
            onChange={(e) => { setFilters({ ...filters, trace_id: e.target.value }); setPage(0); }}
          />
        </div>
        <input
          type="text"
          placeholder="Job ID"
          className="px-2 py-1.5 text-sm border rounded-md w-24 bg-background"
          value={filters.job_id || ''}
          onChange={(e) => { setFilters({ ...filters, job_id: e.target.value }); setPage(0); }}
        />
        <input
          type="text"
          placeholder="Image ID"
          className="px-2 py-1.5 text-sm border rounded-md w-24 bg-background"
          value={filters.image_id || ''}
          onChange={(e) => { setFilters({ ...filters, image_id: e.target.value }); setPage(0); }}
        />
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.operation || ''}
          onChange={(e) => { setFilters({ ...filters, operation: e.target.value }); setPage(0); }}
        >
          <option value="">All operations</option>
          {['tag', 'describe', 'embed', 'generate', 'edit', 'train', 'evaluate', 'summarize', 'expand_prompt'].map((op) => (
            <option key={op} value={op}>{op}</option>
          ))}
        </select>
        <select
          className="px-2 py-1.5 text-sm border rounded-md bg-background"
          value={filters.status || ''}
          onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setPage(0); }}
        >
          <option value="">All statuses</option>
          {['pending', 'executed', 'charged', 'failed', 'cancelled'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Results table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left p-2 font-medium">Trace ID</th>
              <th className="text-left p-2 font-medium">Operation</th>
              <th className="text-left p-2 font-medium">Provider / Model</th>
              <th className="text-left p-2 font-medium">Status</th>
              <th className="text-right p-2 font-medium">Est. Sparks</th>
              <th className="text-right p-2 font-medium">Image ID</th>
              <th className="text-left p-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-8"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr>
            ) : !data?.items?.length ? (
              <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">No operations found</td></tr>
            ) : (
              data.items.map((d: CostDecisionEntry) => (
                <tr key={d.id} className="border-t hover:bg-muted/30 cursor-pointer" onClick={() => d.trace_id && setSelectedTraceId(d.trace_id)}>
                  <td className="p-2 font-mono text-xs">{truncate(d.trace_id, 12)}</td>
                  <td className="p-2">{d.operation}</td>
                  <td className="p-2 text-xs">{d.provider}/{truncate(d.model, 20)}</td>
                  <td className="p-2"><StatusBadge status={d.status} /></td>
                  <td className="p-2 text-right font-mono">{d.estimated_sparks ?? '-'}</td>
                  <td className="p-2 text-right">{d.image_id ?? d.resource_id ?? '-'}</td>
                  <td className="p-2 text-xs text-muted-foreground">{formatDateCompact(d.created_at)}</td>
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

      {/* Trace detail drawer */}
      {selectedTraceId && (
        <TraceDetailDrawer
          traceId={selectedTraceId}
          data={traceData}
          isLoading={traceLoading}
          onClose={() => setSelectedTraceId(null)}
        />
      )}
    </section>
  );
}

function TraceDetailDrawer({
  traceId,
  data,
  isLoading,
  onClose,
}: {
  traceId: string;
  data?: TraceResponse;
  isLoading: boolean;
  onClose: () => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    decisions: true,
    usage: true,
    logs: false,
    transactions: true,
  });

  const toggle = (key: string) => setExpanded({ ...expanded, [key]: !expanded[key] });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/20" />
      <div
        className="relative w-full max-w-2xl bg-background border-l shadow-xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-background border-b p-4 flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Trace Detail</h3>
            <p className="text-xs font-mono text-muted-foreground">{traceId}</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-muted rounded">
            <X className="h-4 w-4" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : !data ? (
          <div className="p-4 text-muted-foreground">No data</div>
        ) : (
          <div className="p-4 space-y-4">
            {/* Decisions */}
            <CollapsibleSection
              title={`Decisions (${data.decisions.length})`}
              expanded={expanded.decisions}
              onToggle={() => toggle('decisions')}
            >
              {data.decisions.map((d) => (
                <div key={d.id} className="border rounded p-3 space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="font-medium">{d.operation}</span>
                    <StatusBadge status={d.status} />
                  </div>
                  <div className="text-muted-foreground">{d.provider}/{d.model}</div>
                  <div className="flex gap-4">
                    <span>Est: {d.estimated_sparks ?? '-'} sparks</span>
                    <span>Tier: {d.catalog_match_tier}</span>
                    {d.image_id && <span>Image: {d.image_id}</span>}
                  </div>
                  {d.error_message && <div className="text-red-500">{d.error_message}</div>}
                </div>
              ))}
            </CollapsibleSection>

            {/* Usage Records */}
            <CollapsibleSection
              title={`Usage Records (${data.usage_records.length})`}
              expanded={expanded.usage}
              onToggle={() => toggle('usage')}
            >
              {data.usage_records.map((r) => (
                <div key={r.id} className="border rounded p-3 space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="font-medium">{r.operation}</span>
                    <span className="font-mono">{r.delta_sparks ?? Math.round(r.charged_cost * 1000)} sparks</span>
                  </div>
                  <div className="text-muted-foreground">{r.provider}/{r.model}</div>
                  <div className="flex gap-4">
                    {r.input_tokens != null && <span>In: {r.input_tokens}</span>}
                    {r.output_tokens != null && <span>Out: {r.output_tokens}</span>}
                    <span>Raw: ${r.raw_cost.toFixed(6)}</span>
                  </div>
                </div>
              ))}
            </CollapsibleSection>

            {/* Pipeline Logs */}
            <CollapsibleSection
              title={`Pipeline Logs (${data.pipeline_logs.length})`}
              expanded={expanded.logs}
              onToggle={() => toggle('logs')}
            >
              {data.pipeline_logs.map((p) => (
                <div key={p.id} className="border rounded p-3 space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="font-medium">{p.category}</span>
                    {p.duration_ms != null && <span>{p.duration_ms.toFixed(0)}ms</span>}
                  </div>
                  <div className="text-muted-foreground break-all">{p.message}</div>
                  {p.provider && <div>{p.provider}/{p.model} — {p.operation}</div>}
                </div>
              ))}
            </CollapsibleSection>

            {/* Transactions */}
            <CollapsibleSection
              title={`Transactions (${data.transactions.length})`}
              expanded={expanded.transactions}
              onToggle={() => toggle('transactions')}
            >
              {data.transactions.map((t) => (
                <div key={t.id} className="border rounded p-3 space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className={cn('font-medium', t.amount < 0 ? 'text-red-500' : 'text-green-500')}>
                      {t.amount > 0 ? '+' : ''}{t.amount.toFixed(2)} sparks
                    </span>
                    <span className="text-muted-foreground">{t.transaction_type}</span>
                  </div>
                  <div className="text-muted-foreground">{t.description}</div>
                </div>
              ))}
            </CollapsibleSection>
          </div>
        )}
      </div>
    </div>
  );
}

function CollapsibleSection({
  title,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-sm font-medium w-full text-left py-1"
      >
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {title}
      </button>
      {expanded && <div className="mt-2 space-y-2">{children}</div>}
    </div>
  );
}
