'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { notFound } from 'next/navigation';
import { Loader2, Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { billingApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { cn, formatDateCompact, formatNumber } from '@/lib/utils';
import type { AdminUserBalance, CostCatalogEntry } from '@/types';

type DateRange = '7d' | '30d' | '90d' | 'all';

function getStartDate(range: DateRange): string | undefined {
  if (range === 'all') return undefined;
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

export default function AdminUsagePage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [dateRange, setDateRange] = useState<DateRange>('30d');
  const [creditUserId, setCreditUserId] = useState<number | null>(null);
  const [creditAmount, setCreditAmount] = useState('');
  const [creditDescription, setCreditDescription] = useState('');
  const [showCatalogForm, setShowCatalogForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState<CostCatalogEntry | null>(null);
  const [catalogForm, setCatalogForm] = useState({
    provider: '',
    model: '',
    operation: '',
    cost_per_input_token: 0,
    cost_per_output_token: 0,
    cost_per_call: 0,
    platform_markup: 1.0,
  });

  // 404 for non-admins
  if (user && user.role !== 'admin') {
    notFound();
  }

  const startDate = getStartDate(dateRange);

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['billing', 'admin', 'summary', dateRange],
    queryFn: () => billingApi.adminGetSummary(startDate),
  });

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ['billing', 'admin', 'users'],
    queryFn: billingApi.adminGetUsers,
  });

  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ['billing', 'admin', 'catalog'],
    queryFn: billingApi.adminGetCatalog,
  });

  const addCreditsMutation = useMutation({
    mutationFn: ({ userId, amount, description }: { userId: number; amount: number; description: string }) =>
      billingApi.adminAddCredits(userId, amount, description),
    onSuccess: () => {
      toast.success('Credits added successfully');
      queryClient.invalidateQueries({ queryKey: ['billing'] });
      setCreditUserId(null);
      setCreditAmount('');
      setCreditDescription('');
    },
    onError: () => toast.error('Failed to add credits'),
  });

  const saveCatalogMutation = useMutation({
    mutationFn: (entry: { id?: number } & typeof catalogForm) => {
      if (entry.id) {
        return billingApi.adminUpdateCatalogEntry(entry.id, entry);
      }
      return billingApi.adminCreateCatalogEntry(entry);
    },
    onSuccess: () => {
      toast.success('Catalog entry saved');
      queryClient.invalidateQueries({ queryKey: ['billing', 'admin', 'catalog'] });
      setShowCatalogForm(false);
      setEditingEntry(null);
      setCatalogForm({ provider: '', model: '', operation: '', cost_per_input_token: 0, cost_per_output_token: 0, cost_per_call: 0, platform_markup: 1.0 });
    },
    onError: () => toast.error('Failed to save catalog entry'),
  });

  const deleteCatalogMutation = useMutation({
    mutationFn: (id: number) => billingApi.adminDeleteCatalogEntry(id),
    onSuccess: () => {
      toast.success('Catalog entry deleted');
      queryClient.invalidateQueries({ queryKey: ['billing', 'admin', 'catalog'] });
    },
    onError: () => toast.error('Failed to delete catalog entry'),
  });

  const sortedUsers = users?.slice().sort((a: AdminUserBalance, b: AdminUserBalance) => a.balance - b.balance) || [];

  // Group catalog by provider
  const catalogByProvider: Record<string, CostCatalogEntry[]> = {};
  catalog?.forEach((entry: CostCatalogEntry) => {
    if (!catalogByProvider[entry.provider]) catalogByProvider[entry.provider] = [];
    catalogByProvider[entry.provider].push(entry);
  });

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Usage Dashboard</h1>
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {(['7d', '30d', '90d', 'all'] as DateRange[]).map((range) => (
            <button
              key={range}
              onClick={() => setDateRange(range)}
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                dateRange === range ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {range === 'all' ? 'All' : range}
            </button>
          ))}
        </div>
      </div>

      {/* Platform Summary */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Platform Summary</h2>
        {summaryLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : summary ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Platform Cost</p>
                <p className="text-2xl font-bold">${formatNumber(summary.total_raw_cost)}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Charged to Users</p>
                <p className="text-2xl font-bold">{formatNumber(summary.total_charged)} credits</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Margin</p>
                <p className="text-2xl font-bold">${formatNumber(summary.margin)}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">API Calls</p>
                <p className="text-2xl font-bold">{summary.record_count}</p>
              </div>
            </div>

            {/* Provider breakdown */}
            {Object.keys(summary.by_provider).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Provider</p>
                <div className="space-y-2">
                  {Object.entries(summary.by_provider)
                    .sort(([, a], [, b]) => b - a)
                    .map(([provider, cost]) => {
                      const pct = summary.total_charged > 0 ? (cost / summary.total_charged) * 100 : 0;
                      return (
                        <div key={provider} className="flex items-center gap-3">
                          <span className="text-sm w-20 text-muted-foreground">{provider}</span>
                          <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                            <div className="bg-primary h-full rounded-full" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-sm font-medium w-24 text-right">{formatNumber(cost)} credits</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}

            {/* Operation breakdown */}
            {Object.keys(summary.by_operation).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Operation</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {Object.entries(summary.by_operation)
                    .sort(([, a], [, b]) => b - a)
                    .map(([op, cost]) => (
                      <div key={op} className="bg-muted rounded-lg px-3 py-2">
                        <p className="text-xs text-muted-foreground">{op}</p>
                        <p className="text-sm font-medium">{cost.toFixed(4)}</p>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </section>

      {/* User Balances */}
      <section>
        <h2 className="text-lg font-semibold mb-4">User Balances</h2>
        {usersLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <div className="bg-card border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left px-4 py-3 font-medium">User</th>
                  <th className="text-right px-4 py-3 font-medium">Balance</th>
                  <th className="text-right px-4 py-3 font-medium">Total Spent</th>
                  <th className="text-right px-4 py-3 font-medium">Last Activity</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedUsers.map((u: AdminUserBalance) => (
                  <tr key={u.user_id} className="border-b last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium">{u.display_name || u.email}</p>
                      {u.display_name && <p className="text-xs text-muted-foreground">{u.email}</p>}
                    </td>
                    <td className={cn('text-right px-4 py-3 font-medium', u.balance < 10 && 'text-red-500')}>
                      {formatNumber(u.balance)}
                    </td>
                    <td className="text-right px-4 py-3">{formatNumber(u.total_spent)}</td>
                    <td className="text-right px-4 py-3 text-muted-foreground">
                      {u.last_activity ? formatDateCompact(u.last_activity) : '-'}
                    </td>
                    <td className="text-right px-4 py-3">
                      <button
                        onClick={() => {
                          setCreditUserId(u.user_id);
                          setCreditAmount('');
                          setCreditDescription('');
                        }}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90"
                      >
                        <Plus className="h-3 w-3" /> Credits
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Add Credits Dialog */}
        {creditUserId !== null && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setCreditUserId(null)}>
            <div className="bg-card border rounded-lg p-6 w-96 space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">Add Credits</h3>
              <p className="text-sm text-muted-foreground">
                User: {sortedUsers.find((u: AdminUserBalance) => u.user_id === creditUserId)?.email}
              </p>
              <div>
                <label className="text-sm font-medium">Amount</label>
                <input
                  type="number"
                  value={creditAmount}
                  onChange={(e) => setCreditAmount(e.target.value)}
                  placeholder="e.g. 1000"
                  className="w-full mt-1 px-3 py-2 bg-background border rounded-md text-sm"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Description</label>
                <input
                  type="text"
                  value={creditDescription}
                  onChange={(e) => setCreditDescription(e.target.value)}
                  placeholder="e.g. Monthly allocation"
                  className="w-full mt-1 px-3 py-2 bg-background border rounded-md text-sm"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setCreditUserId(null)} className="px-4 py-2 text-sm border rounded-md">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    const amt = parseFloat(creditAmount);
                    if (!amt || amt <= 0 || !creditDescription) {
                      toast.error('Please enter a valid amount and description');
                      return;
                    }
                    addCreditsMutation.mutate({ userId: creditUserId, amount: amt, description: creditDescription });
                  }}
                  disabled={addCreditsMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                >
                  {addCreditsMutation.isPending ? 'Adding...' : 'Add Credits'}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Cost Catalog */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Cost Catalog</h2>
          <button
            onClick={() => {
              setEditingEntry(null);
              setCatalogForm({ provider: '', model: '', operation: '', cost_per_input_token: 0, cost_per_output_token: 0, cost_per_call: 0, platform_markup: 1.0 });
              setShowCatalogForm(true);
            }}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" /> Add Entry
          </button>
        </div>

        {catalogLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <div className="space-y-4">
            {Object.entries(catalogByProvider).map(([provider, entries]) => (
              <div key={provider} className="bg-card border rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-muted/50 border-b">
                  <p className="font-medium text-sm capitalize">{provider}</p>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left px-4 py-2 font-medium text-xs text-muted-foreground">Model</th>
                      <th className="text-left px-4 py-2 font-medium text-xs text-muted-foreground">Operation</th>
                      <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Input Token</th>
                      <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Output Token</th>
                      <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Per Call</th>
                      <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Markup</th>
                      <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry: CostCatalogEntry) => (
                      <tr key={entry.id} className="border-b last:border-0">
                        <td className="px-4 py-2 font-mono text-xs">{entry.model}</td>
                        <td className="px-4 py-2">{entry.operation}</td>
                        <td className="text-right px-4 py-2 font-mono text-xs">
                          {entry.cost_per_input_token ? entry.cost_per_input_token.toFixed(10) : '-'}
                        </td>
                        <td className="text-right px-4 py-2 font-mono text-xs">
                          {entry.cost_per_output_token ? entry.cost_per_output_token.toFixed(10) : '-'}
                        </td>
                        <td className="text-right px-4 py-2 font-mono text-xs">
                          {entry.cost_per_call ? entry.cost_per_call.toFixed(4) : '-'}
                        </td>
                        <td className="text-right px-4 py-2">{entry.platform_markup}x</td>
                        <td className="text-right px-4 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => {
                                setEditingEntry(entry);
                                setCatalogForm({
                                  provider: entry.provider,
                                  model: entry.model,
                                  operation: entry.operation,
                                  cost_per_input_token: entry.cost_per_input_token || 0,
                                  cost_per_output_token: entry.cost_per_output_token || 0,
                                  cost_per_call: entry.cost_per_call || 0,
                                  platform_markup: entry.platform_markup,
                                });
                                setShowCatalogForm(true);
                              }}
                              className="p-1 text-muted-foreground hover:text-foreground"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => {
                                if (confirm('Delete this catalog entry?')) {
                                  deleteCatalogMutation.mutate(entry.id);
                                }
                              }}
                              className="p-1 text-muted-foreground hover:text-red-500"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}

        {/* Catalog Form Dialog */}
        {showCatalogForm && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCatalogForm(false)}>
            <div className="bg-card border rounded-lg p-6 w-[480px] space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">{editingEntry ? 'Edit Catalog Entry' : 'New Catalog Entry'}</h3>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium">Provider</label>
                  <input
                    type="text"
                    value={catalogForm.provider}
                    onChange={(e) => setCatalogForm({ ...catalogForm, provider: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Model</label>
                  <input
                    type="text"
                    value={catalogForm.model}
                    onChange={(e) => setCatalogForm({ ...catalogForm, model: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Operation</label>
                  <input
                    type="text"
                    value={catalogForm.operation}
                    onChange={(e) => setCatalogForm({ ...catalogForm, operation: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium">Cost/Input Token</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_input_token}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_input_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Output Token</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_output_token}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_output_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Call</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_call}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_call: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Markup Multiplier</label>
                  <input
                    type="number"
                    step="0.01"
                    value={catalogForm.platform_markup}
                    onChange={(e) => setCatalogForm({ ...catalogForm, platform_markup: parseFloat(e.target.value) || 1.0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowCatalogForm(false)} className="px-4 py-2 text-sm border rounded-md">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (!catalogForm.provider || !catalogForm.model || !catalogForm.operation) {
                      toast.error('Provider, model, and operation are required');
                      return;
                    }
                    saveCatalogMutation.mutate({
                      ...(editingEntry ? { id: editingEntry.id } : {}),
                      ...catalogForm,
                    });
                  }}
                  disabled={saveCatalogMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                >
                  {saveCatalogMutation.isPending ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
