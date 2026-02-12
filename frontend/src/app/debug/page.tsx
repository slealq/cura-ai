'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Trash2, Bug, ChevronRight, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { logsApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { LogEntry } from '@/types';

const LEVEL_COLORS: Record<string, string> = {
  error: 'bg-red-100 text-red-800',
  warning: 'bg-yellow-100 text-yellow-800',
  info: 'bg-blue-100 text-blue-800',
  debug: 'bg-gray-100 text-gray-800',
};

const CATEGORY_LABELS: Record<string, string> = {
  api_call: 'API Call',
  task: 'Task',
  pipeline: 'Pipeline',
  system: 'System',
};

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  if (isToday) return formatTimestamp(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' + formatTimestamp(iso);
}

export default function DebugPage() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<string>('');
  const [level, setLevel] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>('');
  const [page, setPage] = useState(0);
  const limit = 50;

  const { data: logs, isLoading } = useQuery({
    queryKey: ['logs', category, level, search, page],
    queryFn: () =>
      logsApi.list({
        category: category || undefined,
        level: level || undefined,
        search: search || undefined,
        skip: page * limit,
        limit,
      }),
    refetchInterval: 3000,
  });

  const { data: stats } = useQuery({
    queryKey: ['log-stats'],
    queryFn: logsApi.stats,
    refetchInterval: 5000,
  });

  const cleanupMutation = useMutation({
    mutationFn: () => logsApi.cleanup(7),
    onSuccess: (data) => {
      toast.success(`Cleaned up ${data.deleted} old log entries`);
      queryClient.invalidateQueries({ queryKey: ['logs'] });
      queryClient.invalidateQueries({ queryKey: ['log-stats'] });
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(0);
  };

  const totalPages = logs ? Math.ceil(logs.total / limit) : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bug className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Debug Logs</h1>
          {logs && (
            <span className="text-sm text-muted-foreground ml-2">
              {logs.total} entries
            </span>
          )}
        </div>
        <button
          onClick={() => cleanupMutation.mutate()}
          disabled={cleanupMutation.isPending}
          className={cn(
            'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
            'border border-border hover:bg-muted',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
        >
          <Trash2 className="h-4 w-4" />
          {cleanupMutation.isPending ? 'Cleaning...' : 'Cleanup Old Logs'}
        </button>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-lg px-4 py-3 text-center bg-muted">
            <div className="text-2xl font-bold">{stats.total_logs}</div>
            <div className="text-xs font-medium mt-0.5 text-muted-foreground">
              Total Logs
            </div>
          </div>
          <div className="rounded-lg px-4 py-3 text-center bg-blue-100 text-blue-700">
            <div className="text-2xl font-bold">{stats.api_calls}</div>
            <div className="text-xs font-medium mt-0.5">API Calls</div>
          </div>
          <div className="rounded-lg px-4 py-3 text-center bg-red-100 text-red-700">
            <div className="text-2xl font-bold">{stats.errors}</div>
            <div className="text-xs font-medium mt-0.5">Errors</div>
          </div>
          <div className="rounded-lg px-4 py-3 text-center bg-purple-100 text-purple-700">
            <div className="text-2xl font-bold">
              {stats.total_tokens.toLocaleString()}
            </div>
            <div className="text-xs font-medium mt-0.5">Total Tokens</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
          className="px-3 py-2 border border-border rounded-lg text-sm bg-white"
        >
          <option value="">All Categories</option>
          <option value="api_call">API Calls</option>
          <option value="task">Tasks</option>
          <option value="pipeline">Pipeline</option>
          <option value="system">System</option>
        </select>

        <select
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
            setPage(0);
          }}
          className="px-3 py-2 border border-border rounded-lg text-sm bg-white"
        >
          <option value="">All Levels</option>
          <option value="error">Errors</option>
          <option value="warning">Warnings</option>
          <option value="info">Info</option>
          <option value="debug">Debug</option>
        </select>

        <form onSubmit={handleSearch} className="flex-1 flex gap-2">
          <input
            type="text"
            placeholder="Search messages..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="flex-1 px-3 py-2 border border-border rounded-lg text-sm"
          />
          <button
            type="submit"
            className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
          >
            Search
          </button>
        </form>
      </div>

      {/* Log Table */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : logs?.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-muted-foreground">No log entries</p>
          <p className="text-sm text-muted-foreground mt-1">
            Process some images to generate logs
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-border overflow-hidden">
          <table className="w-full">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Time
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Level
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Category
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Message
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Provider / Model
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Tokens
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground">
                  Duration
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {logs?.items.map((log) => (
                <LogRow key={log.id} log={log} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {logs && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-muted-foreground">
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function LogRow({ log }: { log: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const tokens =
    log.input_tokens != null || log.output_tokens != null
      ? (log.input_tokens || 0) + (log.output_tokens || 0)
      : null;

  const hasDetails = log.extra && Object.keys(log.extra).length > 0;
  const extra = log.extra as Record<string, unknown> | null;

  return (
    <>
      <tr
        className={cn(
          'text-xs',
          hasDetails ? 'cursor-pointer' : '',
          expanded ? 'bg-muted/40' : 'hover:bg-muted/30',
        )}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">
          <span className="inline-flex items-center gap-1">
            {hasDetails && (
              expanded
                ? <ChevronDown className="h-3 w-3" />
                : <ChevronRight className="h-3 w-3" />
            )}
            {formatDate(log.created_at)}
          </span>
        </td>
        <td className="px-3 py-2">
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[10px] font-medium uppercase',
              LEVEL_COLORS[log.level] || LEVEL_COLORS.info
            )}
          >
            {log.level}
          </span>
        </td>
        <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
          {CATEGORY_LABELS[log.category] || log.category}
        </td>
        <td className="px-3 py-2 max-w-md">
          <span className="truncate block">{log.message}</span>
        </td>
        <td className="px-3 py-2 whitespace-nowrap">
          {log.provider ? (
            <span className="font-mono text-muted-foreground">
              {log.provider}
              {log.model && (
                <span className="text-foreground ml-1">/ {log.model}</span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
        <td className="px-3 py-2 font-mono whitespace-nowrap">
          {tokens != null ? (
            <span>{tokens.toLocaleString()}</span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
        <td className="px-3 py-2 font-mono whitespace-nowrap">
          {log.duration_ms != null ? (
            <span>
              {log.duration_ms >= 1000
                ? `${(log.duration_ms / 1000).toFixed(1)}s`
                : `${log.duration_ms.toFixed(0)}ms`}
            </span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
      </tr>
      {expanded && extra && (
        <tr>
          <td colSpan={7} className="px-0 py-0">
            <LogDetail log={log} extra={extra} />
          </td>
        </tr>
      )}
    </>
  );
}

function LogDetail({ log, extra }: { log: LogEntry; extra: Record<string, unknown> }) {
  const guidance = extra.guidance as string | null | undefined;
  const requestPrompt = extra.request_prompt as string | undefined;
  const responseContent = extra.response_content as string | undefined;
  const error = extra.error as string | undefined;

  // Parse response content if it's JSON
  let formattedResponse = responseContent;
  if (responseContent) {
    try {
      const parsed = JSON.parse(responseContent);
      formattedResponse = JSON.stringify(parsed, null, 2);
    } catch {
      // not JSON, use as-is
    }
  }

  return (
    <div className="bg-muted/20 border-t border-border px-6 py-4 space-y-4">
      {/* Metadata row */}
      <div className="flex flex-wrap gap-4 text-xs">
        {log.image_id != null && (
          <div>
            <span className="text-muted-foreground">Image ID: </span>
            <span className="font-mono">{log.image_id}</span>
          </div>
        )}
        {log.job_id != null && (
          <div>
            <span className="text-muted-foreground">Job ID: </span>
            <span className="font-mono">{log.job_id}</span>
          </div>
        )}
        {log.operation && (
          <div>
            <span className="text-muted-foreground">Operation: </span>
            <span className="font-mono">{log.operation}</span>
          </div>
        )}
        {log.input_tokens != null && (
          <div>
            <span className="text-muted-foreground">Input tokens: </span>
            <span className="font-mono">{log.input_tokens.toLocaleString()}</span>
          </div>
        )}
        {log.output_tokens != null && (
          <div>
            <span className="text-muted-foreground">Output tokens: </span>
            <span className="font-mono">{log.output_tokens.toLocaleString()}</span>
          </div>
        )}
      </div>

      {/* Guidance */}
      {guidance !== undefined && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">Guidance Used</h4>
          {guidance ? (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs whitespace-pre-wrap">
              {guidance}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground italic">No guidance provided</p>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div>
          <h4 className="text-xs font-semibold text-red-700 mb-1">Error</h4>
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap text-red-800">
            {error}
          </div>
        </div>
      )}

      {/* Request prompt */}
      {requestPrompt && (
        <CollapsibleSection title="Request Prompt" defaultOpen={false}>
          <div className="bg-white border border-border rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap max-h-[400px] overflow-y-auto">
            {requestPrompt}
          </div>
        </CollapsibleSection>
      )}

      {/* Response content */}
      {formattedResponse && (
        <CollapsibleSection title="Model Response" defaultOpen={true}>
          <div className="bg-white border border-border rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap max-h-[400px] overflow-y-auto">
            {formattedResponse}
          </div>
        </CollapsibleSection>
      )}

      {/* Extra fields not already shown */}
      {Object.keys(extra).filter(k => !['guidance', 'request_prompt', 'response_content', 'error'].includes(k)).length > 0 && (
        <CollapsibleSection title="Extra Data" defaultOpen={false}>
          <pre className="bg-white border border-border rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap max-h-[300px] overflow-y-auto">
            {JSON.stringify(
              Object.fromEntries(
                Object.entries(extra).filter(([k]) => !['guidance', 'request_prompt', 'response_content', 'error'].includes(k))
              ),
              null,
              2
            )}
          </pre>
        </CollapsibleSection>
      )}
    </div>
  );
}

function CollapsibleSection({
  title,
  defaultOpen,
  children,
}: {
  title: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className="flex items-center gap-1 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors mb-1"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
      </button>
      {open && children}
    </div>
  );
}
