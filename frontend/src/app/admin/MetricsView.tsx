'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, AlertTriangle, AlertOctagon } from 'lucide-react';
import { billingApi } from '@/lib/api';
import { cn } from '@/lib/utils';

const TIME_RANGES = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
];

function MetricCard({ label, value, suffix, color }: {
  label: string;
  value: string | number;
  suffix?: string;
  color?: 'green' | 'yellow' | 'red' | 'default';
}) {
  const colorClass = {
    green: 'border-green-200 dark:border-green-900',
    yellow: 'border-yellow-200 dark:border-yellow-900',
    red: 'border-red-200 dark:border-red-900',
    default: '',
  }[color || 'default'];

  const valueClass = {
    green: 'text-green-600 dark:text-green-400',
    yellow: 'text-yellow-600 dark:text-yellow-400',
    red: 'text-red-600 dark:text-red-400',
    default: '',
  }[color || 'default'];

  return (
    <div className={cn('border rounded-lg p-3 text-center', colorClass)}>
      <div className={cn('text-2xl font-bold', valueClass)}>{value}{suffix}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

export default function MetricsView() {
  const [hours, setHours] = useState(24);

  const { data, isLoading } = useQuery({
    queryKey: ['admin-metrics', hours],
    queryFn: () => billingApi.adminGetMetrics(hours),
    refetchInterval: 30000,
  });

  const failureColor = (rate: number): 'green' | 'yellow' | 'red' => {
    if (rate < 0.05) return 'green';
    if (rate < 0.10) return 'yellow';
    return 'red';
  };

  const deltaColor = (pct: number): 'green' | 'yellow' | 'red' => {
    const abs = Math.abs(pct);
    if (abs < 10) return 'green';
    if (abs < 30) return 'yellow';
    return 'red';
  };

  return (
    <div className="space-y-4">
      {/* Time range selector */}
      <div className="flex gap-1">
        {TIME_RANGES.map((r) => (
          <button
            key={r.hours}
            className={cn(
              'px-3 py-1 text-sm border rounded-md',
              hours === r.hours ? 'bg-primary text-primary-foreground' : 'hover:bg-muted',
            )}
            onClick={() => setHours(r.hours)}
          >
            {r.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : !data ? (
        <div className="text-muted-foreground text-center py-8">No metrics data</div>
      ) : (
        <>
          {/* Top metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Ops/Hour" value={data.ops_per_hour.toFixed(1)} />
            <MetricCard
              label="Failure Rate"
              value={(data.failure_rate * 100).toFixed(1)}
              suffix="%"
              color={failureColor(data.failure_rate)}
            />
            <MetricCard
              label="Avg Delta"
              value={data.avg_delta_pct.toFixed(1)}
              suffix="%"
              color={deltaColor(data.avg_delta_pct)}
            />
            <MetricCard
              label="Catalog Misses"
              value={data.catalog_miss_count}
              color={data.catalog_miss_count > 5 ? 'yellow' : 'default'}
            />
            <MetricCard
              label="Stale Pending"
              value={data.pending_decisions}
              color={data.pending_decisions > 10 ? 'red' : data.pending_decisions > 0 ? 'yellow' : 'green'}
            />
          </div>

          {/* Alerts */}
          {data.alerts.length > 0 && (
            <div className="space-y-2">
              {data.alerts.map((alert, idx) => (
                <div
                  key={idx}
                  className={cn(
                    'flex items-center gap-2 p-3 rounded-lg text-sm',
                    alert.level === 'critical'
                      ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200'
                      : 'bg-yellow-50 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200',
                  )}
                >
                  {alert.level === 'critical' ? (
                    <AlertOctagon className="h-4 w-4 flex-shrink-0" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                  )}
                  {alert.message}
                </div>
              ))}
            </div>
          )}

          {/* By operation */}
          <div>
            <h3 className="text-sm font-medium mb-2">By Operation</h3>
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-2 font-medium">Operation</th>
                    <th className="text-right p-2 font-medium">Count</th>
                    <th className="text-right p-2 font-medium">Avg Sparks</th>
                    <th className="text-right p-2 font-medium">Failures</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_operation.length === 0 ? (
                    <tr><td colSpan={4} className="text-center py-4 text-muted-foreground">No data</td></tr>
                  ) : (
                    data.by_operation.map((row) => (
                      <tr key={row.operation} className="border-t">
                        <td className="p-2">{row.operation}</td>
                        <td className="p-2 text-right font-mono">{row.count}</td>
                        <td className="p-2 text-right font-mono">{row.avg_sparks.toFixed(1)}</td>
                        <td className={cn('p-2 text-right font-mono', row.failure_count > 0 ? 'text-red-600 dark:text-red-400' : '')}>
                          {row.failure_count}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* By provider */}
          <div>
            <h3 className="text-sm font-medium mb-2">By Provider</h3>
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-2 font-medium">Provider</th>
                    <th className="text-right p-2 font-medium">Count</th>
                    <th className="text-right p-2 font-medium">Avg Sparks</th>
                    <th className="text-right p-2 font-medium">Failures</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_provider.length === 0 ? (
                    <tr><td colSpan={4} className="text-center py-4 text-muted-foreground">No data</td></tr>
                  ) : (
                    data.by_provider.map((row) => (
                      <tr key={row.provider} className="border-t">
                        <td className="p-2">{row.provider}</td>
                        <td className="p-2 text-right font-mono">{row.count}</td>
                        <td className="p-2 text-right font-mono">{row.avg_sparks.toFixed(1)}</td>
                        <td className={cn('p-2 text-right font-mono', row.failure_count > 0 ? 'text-red-600 dark:text-red-400' : '')}>
                          {row.failure_count}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
